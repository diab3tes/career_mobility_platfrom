"""Privacy features: consent before sending a CV (P4), contact details removed before sending (P3),
"delete my data" (P1) and the retention purge (P2). The LLM is always faked."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from ai import client as ai_client
from ai import limits
from ai.models import AIAssessmentCache, UserAIAssessment
from ai.redact import EMAIL_TAG, LINK_TAG, PHONE_TAG, redact_contact_details
from ai.schemas import ExtractedProfile
from opportunities.models import Opportunity
from profiles.models import Profile
from profiles.sample import SAMPLE_PROFILE
from shortlist.models import ShortlistItem

from .pdf_utils import CV_TEXT, make_pdf

pytestmark = pytest.mark.django_db
CREDS = dict(AI_PROVIDER="groq", GROQ_API_KEY="test-key", GROQ_MODEL="openai/gpt-oss-20b")


class FakeLLM:
    def __init__(self):
        self.sent = []

    def with_structured_output(self, schema, **kw):
        return self

    def invoke(self, messages):
        self.sent.append(messages[-1].content)
        return {"raw": None, "parsed": ExtractedProfile(skills=["Excel"]), "parsing_error": None}


@pytest.fixture
def live(client, settings):
    for k, v in CREDS.items():
        setattr(settings, k, v)
    s = client.session
    s["ai_mode"] = "live"
    s.save()
    return client


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(ai_client, "get_chat_model", lambda **kw: llm)
    return llm


def cv(text=CV_TEXT):
    return SimpleUploadedFile("cv.pdf", make_pdf([text]), content_type="application/pdf")


# ---------------- P4: consent ----------------
def test_live_upload_without_consent_is_refused_before_any_processing(live, fake_llm):
    r = live.post("/profile/cv/", {"cv": cv()})
    assert r.status_code == 400 and "agree that your CV text is sent to Groq" in r.context["cv_error"]
    assert fake_llm.sent == [] and live.session.get(limits.SESSION_KEY, 0) == 0


def test_live_upload_with_consent_proceeds(live, fake_llm):
    r = live.post("/profile/cv/", {"cv": cv(), "consent": "yes"})
    assert r.status_code == 200 and len(fake_llm.sent) == 1


def test_mock_upload_needs_no_consent_and_shows_no_checkbox(client, fake_llm):
    assert 'name="consent"' not in client.get("/").content.decode()
    r = client.post("/profile/cv/", {"cv": cv()})
    assert r.status_code == 200 and fake_llm.sent == []  # mock: nothing is sent anywhere


def test_live_page_shows_required_consent_naming_provider(live):
    html = live.get("/").content.decode()
    assert 'name="consent" value="yes" required' in html and "sent to Groq (openai/gpt-oss-20b)" in html


# ---------------- P3: contact details removed ----------------
@pytest.mark.parametrize(
    "text,kept,removed",
    [
        ("Mail amira.rahman@example.com now", "Mail", "amira.rahman@example.com"),
        ("Call +44 20 7946 0958 today", "Call", "7946"),
        ("Phone: 01712345678.", "Phone:", "01712345678"),
        ("See linkedin.com/in/amira and https://github.com/amira", "See", "github.com"),
    ],
)
def test_contact_details_are_replaced(text, kept, removed):
    out, _ = redact_contact_details(text)
    assert kept in out and removed not in out


@pytest.mark.parametrize(
    "text",
    ["Operations Assistant, 2022-2024", "BBA 2016 - 2020", "IELTS 7.5", "budget of 120,000 BDT", "12 schools, 2019 to 2023"],
)
def test_dates_scores_and_amounts_are_kept(text):
    assert redact_contact_details(text) == (text, {"emails": 0, "phones": 0, "links": 0})


def test_live_extraction_never_sends_contact_details(live, fake_llm):
    text = CV_TEXT + " Contact: amira@example.com, +00 000 000 000, linkedin.com/in/amira-r"
    r = live.post("/profile/cv/", {"cv": cv(text), "consent": "yes"})
    sent = fake_llm.sent[0]
    assert "amira@example.com" not in sent and "000 000 000" not in sent and "linkedin.com" not in sent
    assert EMAIL_TAG in sent and PHONE_TAG in sent and LINK_TAG in sent
    assert "Bachelor of Business Administration" in sent  # the useful content still goes
    assert "Removed before sending: 1 email address, 1 phone number, 1 link." in r.context["cv_result"]["notice"]


# ---------------- P1: delete my data ----------------
def _user_with_data(c):
    call_command("seed_opportunities")
    p = Profile.objects.create(**SAMPLE_PROFILE)
    s = c.session
    s["profile_id"] = p.pk
    s.save()
    o = Opportunity.objects.first()
    ShortlistItem.objects.create(profile=p, opportunity=o)
    c.post(f"/api/opportunities/{o.pk}/ai-assessment/")  # mock assessment, saved for this user
    return p, o


def test_delete_my_data_removes_profile_shortlist_assessments_and_cache(client):
    from ai.services import profile_fingerprint
    from matching.adapters import profile_to_data

    p, o = _user_with_data(client)
    AIAssessmentCache.objects.create(key="k" * 64, opportunity=o, result={}, profile_hash=profile_fingerprint(profile_to_data(p)))
    other_cache = AIAssessmentCache.objects.create(key="z" * 64, opportunity=o, result={}, profile_hash="someone-else")
    assert UserAIAssessment.objects.filter(user=p).exists()

    r = client.post("/profile/delete/")
    assert r.status_code == 302 and r["Location"] == "/"
    assert not Profile.objects.filter(pk=p.pk).exists()
    assert not ShortlistItem.objects.exists() and not UserAIAssessment.objects.exists()
    assert list(AIAssessmentCache.objects.all()) == [other_cache]  # only this profile's cache rows go
    assert "profile_id" not in client.session  # a fresh session
    assert "have been deleted" in client.get("/").content.decode()
    assert Opportunity.objects.count() == 12  # the catalogue is untouched


def test_delete_only_affects_the_requesting_user(client):
    _user_with_data(client)
    other = Client()
    other_profile = Profile.objects.create(**SAMPLE_PROFILE)
    s = other.session
    s["profile_id"] = other_profile.pk
    s.save()
    other.post("/profile/delete/")
    assert Profile.objects.count() == 1 and not Profile.objects.filter(pk=other_profile.pk).exists()


def test_delete_requires_post_and_works_without_a_profile(client):
    assert client.get("/profile/delete/").status_code == 405
    assert client.post("/profile/delete/").status_code == 302


def test_delete_button_only_shown_with_a_profile(client):
    assert 'action="/profile/delete/"' not in client.get("/").content.decode()
    _user_with_data(client)
    assert 'action="/profile/delete/"' in client.get("/").content.decode()


# ---------------- P2: retention purge ----------------
def _age(queryset, field, days):
    queryset.update(**{field: timezone.now() - timedelta(days=days)})


def test_purge_removes_only_expired_data(client, settings):
    settings.DATA_RETENTION_DAYS = 30
    old_p, o = _user_with_data(client)
    _age(Profile.objects.filter(pk=old_p.pk), "last_active_at", 31)

    recent = Profile.objects.create(**SAMPLE_PROFILE)
    recent_item = ShortlistItem.objects.create(profile=recent, opportunity=o)
    old_inactive = UserAIAssessment.objects.create(user=recent, opportunity=o, assessment_data={}, is_active=False)
    _age(UserAIAssessment.objects.filter(pk=old_inactive.pk), "created_at", 40)
    active = UserAIAssessment.objects.create(user=recent, opportunity=o, assessment_data={}, is_active=True)
    old_cache = AIAssessmentCache.objects.create(key="o" * 64, opportunity=o, result={})
    _age(AIAssessmentCache.objects.filter(pk=old_cache.pk), "created_at", 31)
    new_cache = AIAssessmentCache.objects.create(key="n" * 64, opportunity=o, result={})

    call_command("purge_expired_data")

    assert list(Profile.objects.all()) == [recent]
    assert list(ShortlistItem.objects.all()) == [recent_item]
    assert list(UserAIAssessment.objects.all()) == [active]
    assert list(AIAssessmentCache.objects.all()) == [new_cache]
    assert Opportunity.objects.count() == 12


def test_purge_dry_run_deletes_nothing(client, capsys):
    p, _ = _user_with_data(client)
    _age(Profile.objects.filter(pk=p.pk), "last_active_at", 400)
    call_command("purge_expired_data", "--dry-run")
    assert Profile.objects.filter(pk=p.pk).exists()
    assert "Would delete" in capsys.readouterr().out


def test_purge_days_option_overrides_setting(client):
    p, _ = _user_with_data(client)
    _age(Profile.objects.filter(pk=p.pk), "last_active_at", 3)
    call_command("purge_expired_data", "--days", "2")
    assert not Profile.objects.filter(pk=p.pk).exists()


def test_visiting_refreshes_last_active_so_active_users_are_kept(client):
    p, _ = _user_with_data(client)
    _age(Profile.objects.filter(pk=p.pk), "last_active_at", 29)
    client.get("/recommendations/")
    p.refresh_from_db()
    assert timezone.now() - p.last_active_at < timedelta(minutes=1)
    call_command("purge_expired_data")
    assert Profile.objects.filter(pk=p.pk).exists()


def test_activity_refresh_does_not_touch_updated_at(client):
    p, _ = _user_with_data(client)
    _age(Profile.objects.filter(pk=p.pk), "last_active_at", 2)
    before = Profile.objects.get(pk=p.pk).updated_at
    client.get("/")
    assert Profile.objects.get(pk=p.pk).updated_at == before
