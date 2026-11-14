"""One visitor can never see or change another visitor's data, on any page or endpoint.

Profiles are found only through the server-side session (profile_id stored in the session); the only id a
URL carries is the opportunity id, and opportunities are the public catalogue.
"""

import json

import pytest
from django.core.management import call_command
from django.test import Client

from ai.models import UserAIAssessment
from opportunities.models import Opportunity
from profiles.models import Profile
from profiles.sample import SAMPLE_PROFILE
from shortlist.models import ShortlistItem

pytestmark = pytest.mark.django_db
SECRET = "Zebra-Quantum-Skill"  # appears only in visitor A's profile


def _visitor_with_profile(**over):
    c = Client()
    p = Profile.objects.create(**{**SAMPLE_PROFILE, **over})
    s = c.session
    s["profile_id"] = p.pk
    s.save()
    return c, p


@pytest.fixture
def two_visitors():
    call_command("seed_opportunities")
    a, pa = _visitor_with_profile(skills=[SECRET, "Excel"], education_field="Secret Studies")
    o = Opportunity.objects.get(title="Programme Assistant")
    a.post(f"/api/shortlist/{o.pk}/")
    a.post(f"/api/opportunities/{o.pk}/ai-assessment/")  # saved assessment for A
    b, pb = _visitor_with_profile()
    return a, pa, b, pb, o


def test_other_visitor_never_sees_a_profile_data(two_visitors):
    a, pa, b, pb, o = two_visitors
    pages = [
        b.get("/"),
        b.get("/recommendations/"),
        b.get("/api/recommendations/"),
        b.get(f"/api/opportunities/{o.pk}/"),
        b.get("/shortlist/"),
        b.post(f"/api/opportunities/{o.pk}/ai-assessment/"),
    ]
    for r in pages:
        body = r.content.decode()
        assert SECRET not in body and "Secret Studies" not in body

    # B's own views show B's state, not A's: nothing shortlisted, and B's assessment is B's own row.
    recs = b.get("/api/recommendations/").json()
    assert not any(r["shortlisted"] for r in recs["results"])
    assert "Programme Assistant" not in b.get("/shortlist/").content.decode()
    assert UserAIAssessment.objects.filter(user=pa).count() == 1
    assert UserAIAssessment.objects.filter(user=pb).count() == 1


def test_other_visitor_cannot_change_a_data(two_visitors):
    a, pa, b, pb, o = two_visitors
    b.delete(f"/api/shortlist/{o.pk}/")             # API remove
    b.post(f"/shortlist/{o.pk}/remove/")             # page remove
    b.post(f"/api/opportunities/{o.pk}/ai-assessment/", data=json.dumps({"refresh": True}), content_type="application/json")
    b.post("/", {"education_level": "doctorate", "years_experience": "9", "skills": "Hacking",
                 "currently_enrolled_student": "unknown", "work_authorisation_status": "unknown",
                 "lang-TOTAL_FORMS": "0", "lang-INITIAL_FORMS": "0", "lang-MIN_NUM_FORMS": "0", "lang-MAX_NUM_FORMS": "10"})
    b.post("/profile/delete/")                       # deletes only B

    pa.refresh_from_db()
    assert SECRET in pa.skills and pa.education_level == "bachelor"
    assert ShortlistItem.objects.filter(profile=pa, opportunity=o).exists()
    assert UserAIAssessment.objects.filter(user=pa, is_active=True).count() == 1
    assert not Profile.objects.filter(pk=pb.pk).exists()


def test_visitor_without_a_session_sees_nothing_personal(two_visitors):
    stranger = Client()
    assert stranger.get("/api/recommendations/").json() == {"has_profile": False, "results": [], "assessments": {}}
    assert stranger.get(f"/api/opportunities/{two_visitors[4].pk}/").json()["match"] is None
    assert SECRET not in stranger.get("/shortlist/").content.decode()


def test_profile_id_cannot_be_chosen_by_the_client(two_visitors):
    a, pa, b, pb, o = two_visitors
    # Query strings and form fields named like the session key are ignored; only the session decides.
    for r in (b.get(f"/api/recommendations/?profile_id={pa.pk}"), b.get(f"/?profile_id={pa.pk}")):
        assert SECRET not in r.content.decode()
    assert b.session["profile_id"] == pb.pk
