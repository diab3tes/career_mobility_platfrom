"""CV pipeline tests. The LLM is always faked; nothing calls a real AI provider."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from ai import client, limits
from ai.cv_extractor import CVRejected, extract_text, live_extract, max_bytes
from ai.schemas import ExtractedProfile
from profiles.models import Profile

from .pdf_utils import CV_TEXT, make_pdf

pytestmark = pytest.mark.django_db
CREDS = dict(AI_PROVIDER="groq", GROQ_API_KEY="test-key", GROQ_MODEL="openai/gpt-oss-20b")

GOOD = {
    "education_level": "bachelor",
    "education_field": "Business Administration",
    "years_experience": 2,
    "skills": ["Excel", "Reporting"],
    "languages": [{"language": "English", "level": "professional"}],
    "experience_areas": [],
    "preferred_countries": [],
    "career_interests": ["business operations"],
}


class FakeLLM:
    """Stands in for ChatWatsonx. Each output is a dict like with_structured_output(include_raw=True) returns,
    or an Exception to raise."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        assert schema is ExtractedProfile and kwargs.get("include_raw") is True
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def ok(data):
    return {"raw": None, "parsed": data, "parsing_error": None}


def bad(err="bad json"):
    return {"raw": None, "parsed": None, "parsing_error": ValueError(err)}


@pytest.fixture
def no_llm(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("The model must not be called")

    monkeypatch.setattr(client, "get_chat_model", boom)


@pytest.fixture
def fake_llm(monkeypatch):
    holder = {}

    def install(outputs):
        holder["llm"] = FakeLLM(outputs)
        monkeypatch.setattr(client, "get_chat_model", lambda **kw: holder["llm"])
        return holder["llm"]

    return install


@pytest.fixture
def live(client, settings):
    for k, v in CREDS.items():
        setattr(settings, k, v)
    s = client.session
    s["ai_mode"] = "live"
    s.save()
    return client


def pdf_upload(pages=None, name="cv.pdf"):
    return SimpleUploadedFile(name, make_pdf(pages or [CV_TEXT]), content_type="application/pdf")


def upload(c, f, consent=True):
    data = {"cv": f}
    if consent:
        data["consent"] = "yes"  # required in Live mode; ignored in Mock mode
    return c.post("/profile/cv/", data)


# ---------- validation (no model call) ----------
def test_non_pdf_rejected(client, no_llm):
    r = upload(client, SimpleUploadedFile("cv.txt", b"hello", content_type="text/plain"))
    assert r.status_code == 400 and "Only PDF" in r.context["cv_error"]


def test_pdf_extension_with_non_pdf_content_rejected(client, no_llm):
    r = upload(client, SimpleUploadedFile("cv.pdf", b"PK\x03\x04 not a pdf", content_type="application/pdf"))
    assert r.status_code == 400 and "not a valid PDF" in r.context["cv_error"]


def test_oversized_pdf_rejected(client, no_llm):
    big = SimpleUploadedFile("cv.pdf", b"%PDF-1.4\n" + b"0" * max_bytes(), content_type="application/pdf")
    r = upload(client, big)
    assert r.status_code == 400 and "10 MB" in r.context["cv_error"]


def test_missing_file_rejected(client, no_llm):
    r = client.post("/profile/cv/", {})
    assert r.status_code == 400 and "Choose a PDF" in r.context["cv_error"]


def test_low_text_pdf_rejected_opens_manual_form_and_makes_no_model_call(live, no_llm):
    r = upload(live, pdf_upload(["Jordan Example", "Curriculum vitae page two"]))
    assert r.status_code == 400
    assert "Only text-based PDFs are supported" in r.context["cv_error"]
    assert "form" in r.context and not r.context["form"].is_bound  # manual form is shown
    assert live.session.get(limits.SESSION_KEY, 0) == 0  # no live call was counted


def test_unreadable_pdf_rejected(client, no_llm):
    r = upload(client, SimpleUploadedFile("cv.pdf", b"%PDF-1.4\ngarbage", content_type="application/pdf"))
    assert r.status_code == 400 and r.context["cv_error"]


def test_text_extraction_counts_words_per_page():
    doc = extract_text(make_pdf([CV_TEXT, CV_TEXT]))
    assert doc.pages == 2 and doc.words_per_page > 50 and "Business Administration" in doc.text


# ---------- mock mode ----------
def test_mock_mode_prefills_sample_profile_without_saving(client, no_llm):
    r = upload(client, pdf_upload())
    assert r.status_code == 200
    assert r.context["cv_result"]["source"] == "mock"
    html = r.content.decode()
    assert html.count("Mock AI output") == 1 and "Stakeholder communication" in html
    assert Profile.objects.count() == 0
    # The pre-filled page lives at /profile/cv/; its Save must post to the profile view, not back to the upload.
    assert 'action="/" novalidate' in html


def test_saving_after_cv_prefill_creates_profile(client, no_llm):
    upload(client, pdf_upload())
    data = {
        "education_level": "bachelor", "years_experience": "2", "skills": "Excel",
        "currently_enrolled_student": "unknown", "work_authorisation_status": "unknown",
        "lang-TOTAL_FORMS": "0", "lang-INITIAL_FORMS": "0", "lang-MIN_NUM_FORMS": "0", "lang-MAX_NUM_FORMS": "10",
    }
    r = client.post("/", data)
    assert r.status_code == 302 and Profile.objects.count() == 1


# ---------- live mode with a fake model ----------
def test_live_success_marks_ai_filled_and_empty_fields(live, fake_llm):
    llm = fake_llm([ok(ExtractedProfile(**GOOD))])
    r = upload(live, pdf_upload())
    assert r.status_code == 200 and len(llm.calls) == 1
    form = r.context["form"]
    assert form.initial["skills"] == ["Excel", "Reporting"]
    assert form.fields["skills"].ai_state == "filled"
    assert form.fields["preferred_countries"].ai_state == "empty"
    assert form.fields["work_authorisation_status"].ai_state == "never"
    assert form.initial["work_authorisation_status"] == "unknown"
    assert form.initial["currently_enrolled_student"] == "unknown"
    assert r.context["cv_result"]["source"] == "live"
    assert "AI-filled" in r.content.decode() and "Not found in CV" in r.content.decode()
    assert Profile.objects.count() == 0
    assert live.session[limits.SESSION_KEY] == 1
    sent = llm.calls[0][1].content
    assert "Business Administration" in sent  # the CV text, delimited as data


def test_live_invalid_output_retries_once_with_errors_then_succeeds(live, fake_llm):
    llm = fake_llm([ok({**GOOD, "years_experience": 99}), ok(GOOD)])
    r = upload(live, pdf_upload())
    assert r.status_code == 200 and len(llm.calls) == 2
    retry_msg = llm.calls[1][-1].content
    assert "years_experience" in retry_msg and "could not be validated" in retry_msg


def test_live_invalid_twice_opens_manual_form(live, fake_llm):
    llm = fake_llm([bad(), ok({**GOOD, "education_level": "wizard"})])
    r = upload(live, pdf_upload())
    assert r.status_code == 400 and len(llm.calls) == 2
    assert "could not produce a valid profile" in r.context["cv_error"]


def test_live_service_error_opens_manual_form(live, fake_llm):
    fake_llm([ConnectionError("network down")])
    r = upload(live, pdf_upload())
    assert r.status_code == 400 and "AI service returned an error" in r.context["cv_error"]


def test_live_timeout_is_handled(live, fake_llm, monkeypatch):
    fake_llm([ok(GOOD)])

    def slow_call(fn, timeout=None):
        raise client.LLMUnavailable("The AI service did not respond within 45 seconds.")

    monkeypatch.setattr(client, "call_with_timeout", slow_call)
    r = upload(live, pdf_upload())
    assert r.status_code == 400 and "did not respond" in r.context["cv_error"]


def test_call_with_timeout_converts_timeout():
    import time

    with pytest.raises(client.LLMUnavailable, match="did not respond"):
        client.call_with_timeout(lambda: time.sleep(0.5), timeout=0.05)


def test_live_session_limit_stops_calls(live, no_llm):
    s = live.session
    s[limits.SESSION_KEY] = limits.limit()
    s.save()
    r = upload(live, pdf_upload())
    assert r.status_code == 400 and "limit" in r.context["cv_error"]


@override_settings(**CREDS)
def test_extracted_profile_ignores_eligibility_keys_from_model(fake_llm):
    fake_llm([ok({**GOOD, "work_authorisation": ["Germany"], "currently_enrolled_student": "yes"})])
    profile = live_extract(CV_TEXT)
    dumped = profile.model_dump()
    assert "work_authorisation" not in dumped and "currently_enrolled_student" not in dumped


def test_cv_rejected_message_is_user_safe():
    with pytest.raises(CVRejected):
        from ai.cv_extractor import check_enough_text, ExtractedText

        check_enough_text(ExtractedText(text="", pages=0))
