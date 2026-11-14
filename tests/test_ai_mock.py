import json

import pytest
from django.test import override_settings

from ai.mock import mock_assessment, mock_extracted_profile, mock_extraction
from ai.schemas import ExtractedProfile
from matching.engine import match
from matching.schemas import OpportunityData, ProfileData
from profiles.sample import SAMPLE_PROFILE

CREDS = dict(AI_PROVIDER="groq", GROQ_API_KEY="test-key", GROQ_MODEL="openai/gpt-oss-20b")
NO_CREDS = dict(AI_PROVIDER="groq", GROQ_API_KEY="")


def post_mode(client, mode):
    return client.post("/api/ai-mode/", data=json.dumps({"mode": mode}), content_type="application/json")


# ---------- toggle ----------
@pytest.mark.django_db
@override_settings(**NO_CREDS)
def test_default_is_mock_and_live_is_locked_without_credentials(client):
    html = client.get("/").content.decode()
    assert "Locked to Mock" in html
    r = post_mode(client, "live")
    assert r.status_code == 409 and r.json()["mode"] == "mock" and r.json()["live_available"] is False


@pytest.mark.django_db
@override_settings(**CREDS)
def test_toggle_switches_with_credentials(client):
    assert post_mode(client, "live").json() == {"mode": "live", "live_available": True}
    assert 'value="live" aria-pressed="true"' in client.get("/").content.decode()
    assert post_mode(client, "mock").json()["mode"] == "mock"


@pytest.mark.django_db
def test_stale_live_session_falls_back_to_mock_when_credentials_removed(client):
    with override_settings(**CREDS):
        post_mode(client, "live")
    with override_settings(**NO_CREDS):
        assert 'value="mock" aria-pressed="true"' in client.get("/").content.decode()


@pytest.mark.django_db
def test_invalid_mode_rejected(client):
    assert post_mode(client, "turbo").status_code == 400
    assert client.post("/api/ai-mode/", data="{bad", content_type="application/json").status_code == 400
    assert client.get("/api/ai-mode/").status_code == 405


@pytest.mark.django_db
@override_settings(**CREDS)
def test_form_post_fallback_redirects_back_safely(client):
    r = client.post("/api/ai-mode/", {"mode": "live", "next": "/recommendations/"})
    assert r.status_code == 302 and r["Location"] == "/recommendations/"
    r = client.post("/api/ai-mode/", {"mode": "mock", "next": "https://evil.example/"})
    assert r["Location"] == "/"


# ---------- mock provider ----------
def test_mock_extraction_is_sample_profile_without_eligibility_fields():
    resp = mock_extraction()
    assert resp.source == "mock" and "Mock AI output" in resp.notice
    p = resp.profile
    assert p.skills == SAMPLE_PROFILE["skills"] and p.education_level == "bachelor"
    assert "work_authorisation" not in ExtractedProfile.model_fields
    assert "currently_enrolled_student" not in ExtractedProfile.model_fields
    assert "skills" in mock_extracted_profile().filled_fields()


def _result(**opp):
    profile = ProfileData(**{k: v for k, v in SAMPLE_PROFILE.items()})
    return match(profile, OpportunityData(title="Role", country="Germany", **opp))


def test_mock_assessment_is_deterministic_and_labelled():
    r = _result(required_skills=["excel", "reporting"])
    a, b = mock_assessment(r), mock_assessment(r)
    assert a.model_dump() == b.model_dump()
    assert a.source == "mock" and a.assessment.summary.startswith("Mock AI output")
    assert a.assessment.fit == "strong"


def test_mock_assessment_fit_follows_rules_and_blocker_is_weak():
    weak = _result(required_skills=["python", "java", "go"], min_years_experience=10)
    assert mock_assessment(weak).assessment.fit == "weak"
    blocked = _result(
        required_skills=["excel"],
        language_requirements=[{"language": "German", "level": "professional", "mandatory": True}],
    )
    out = mock_assessment(blocked).assessment
    assert out.fit == "weak" and any("German" in c for c in out.considerations)


def test_fallback_source_carries_notice():
    resp = mock_assessment(_result(required_skills=["excel"]), source="fallback")
    assert resp.source == "fallback" and "unavailable" in resp.notice
