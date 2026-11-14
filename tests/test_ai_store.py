"""Table user_ai_assessment: assessments survive reloads, one active row per user and opportunity."""

import json

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client

from ai.models import UserAIAssessment
from opportunities.models import Opportunity
from profiles.models import Profile
from profiles.sample import SAMPLE_PROFILE

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(client):
    call_command("seed_opportunities")
    p = Profile.objects.create(**SAMPLE_PROFILE)
    s = client.session
    s["profile_id"] = p.pk
    s.save()
    return p


def oid(title):
    return Opportunity.objects.get(title=title).pk


def post_ai(c, pk, refresh=False):
    if refresh:
        return c.post(f"/api/opportunities/{pk}/ai-assessment/", data=json.dumps({"refresh": True}), content_type="application/json")
    return c.post(f"/api/opportunities/{pk}/ai-assessment/")


def test_assessment_is_saved_with_user_and_opportunity(client, setup):
    pk = oid("Programme Assistant")
    body = post_ai(client, pk).json()
    row = UserAIAssessment.objects.get()
    assert row.user_id == setup.pk and row.opportunity_id == pk and row.is_active
    assert row.assessment_data["source"] == "mock" and row.assessment_data["assessment"]["fit"] in {"strong", "moderate", "weak"}
    assert row.created_at and row.updated_at
    assert body["stored"] is False and body["saved_at"]


def test_saved_assessment_comes_back_after_reload(client, setup):
    pk = oid("Business Analyst")
    first = post_ai(client, pk).json()
    # A fresh page load (initial data) and the JSON endpoint both carry it.
    page = client.get("/api/recommendations/").json()
    saved = page["assessments"][str(pk)]
    assert saved["assessment"] == first["assessment"] and saved["stored"] is True
    assert saved["rule"]["eligibility"] == "no_stated_constraint"
    assert str(oid("Programme Assistant")) not in page["assessments"]


def test_second_request_returns_saved_row_without_running_again(client, setup):
    pk = oid("Programme Assistant")
    post_ai(client, pk)
    again = post_ai(client, pk).json()
    assert again["stored"] is True and UserAIAssessment.objects.count() == 1


def test_run_again_keeps_history_with_one_active_row(client, setup):
    pk = oid("Programme Assistant")
    post_ai(client, pk)
    post_ai(client, pk, refresh=True)
    rows = UserAIAssessment.objects.filter(user=setup, opportunity_id=pk)
    assert rows.count() == 2 and rows.filter(is_active=True).count() == 1


def test_database_allows_only_one_active_row_per_pair(setup):
    o = Opportunity.objects.first()
    UserAIAssessment.objects.create(user=setup, opportunity=o, assessment_data={})
    with pytest.raises(IntegrityError), transaction.atomic():
        UserAIAssessment.objects.create(user=setup, opportunity=o, assessment_data={})
    UserAIAssessment.objects.create(user=setup, opportunity=o, assessment_data={}, is_active=False)  # history is fine


def _profile_post(**over):
    data = {
        "education_level": "bachelor", "education_field": "Business Administration", "years_experience": str(SAMPLE_PROFILE["years_experience"]),
        "skills": ", ".join(SAMPLE_PROFILE["skills"]), "experience_areas": ", ".join(SAMPLE_PROFILE["experience_areas"]),
        "preferred_countries": ", ".join(SAMPLE_PROFILE["preferred_countries"]),
        "career_interests": ", ".join(SAMPLE_PROFILE["career_interests"]),
        "currently_enrolled_student": "unknown", "work_authorisation_status": "unknown", "work_authorisation": "",
        "lang-TOTAL_FORMS": "2", "lang-INITIAL_FORMS": "0", "lang-MIN_NUM_FORMS": "0", "lang-MAX_NUM_FORMS": "10",
        "lang-0-language": "Bengali", "lang-0-level": "native", "lang-1-language": "English", "lang-1-level": "professional",
    }
    data.update(over)
    return data


def test_editing_the_profile_deactivates_saved_assessments(client, setup):
    post_ai(client, oid("Programme Assistant"))
    client.post("/", _profile_post())  # same data: nothing changed, keep them
    assert UserAIAssessment.objects.filter(is_active=True).count() == 1
    client.post("/", _profile_post(years_experience=str(SAMPLE_PROFILE["years_experience"] + 2)))  # real change
    assert UserAIAssessment.objects.filter(is_active=True).count() == 0
    assert UserAIAssessment.objects.count() == 1  # kept as history
    assert client.get("/api/recommendations/").json()["assessments"] == {}


def test_assessments_are_private_to_each_user(client, setup):
    post_ai(client, oid("Programme Assistant"))
    other = Client()
    assert other.get("/api/recommendations/").json()["assessments"] == {}


def test_invalid_json_body_rejected(client, setup):
    r = client.post(f"/api/opportunities/{oid('Programme Assistant')}/ai-assessment/", data="{bad", content_type="application/json")
    assert r.status_code == 400
