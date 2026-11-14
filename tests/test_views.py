import json
import re

import pytest
from django.core.management import call_command
from django.test import Client

from opportunities.models import Opportunity
from profiles.models import Profile
from profiles.sample import SAMPLE_PROFILE
from shortlist.models import ShortlistItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_opportunities")


@pytest.fixture
def with_profile(client, seeded):
    p = Profile.objects.create(**SAMPLE_PROFILE)
    s = client.session
    s["profile_id"] = p.pk
    s.save()
    return p


def opp_id(title):
    return Opportunity.objects.get(title=title).pk


def test_recommendations_without_profile(client, seeded):
    body = client.get("/api/recommendations/").json()
    assert body == {"has_profile": False, "results": [], "assessments": {}}
    page = client.get("/recommendations/")
    assert page.status_code == 200 and 'id="initial-data"' in page.content.decode()


def test_recommendations_ranked_for_sample(client, with_profile):
    results = client.get("/api/recommendations/").json()["results"]
    assert len(results) == 12
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert {r["title"] for r in results[:3]} == {"Programme Assistant", "Operations Coordinator", "Project Support Officer"}
    first = results[0]
    for key in ("score", "eligibility", "eligibility_label", "strengths", "gaps", "criteria", "shortlisted"):
        assert key in first


def test_page_embeds_initial_data(client, with_profile):
    html = client.get("/recommendations/").content.decode()
    match = re.search(r'<script id="initial-data"[^>]*>(.*?)</script>', html, re.S)
    data = json.loads(match.group(1))
    assert data["has_profile"] is True and len(data["results"]) == 12
    # The React code swaps the first "/0/" for the real id, so each template must contain it exactly once.
    for name in ("detail", "shortlist", "ai"):
        assert data["urls"][name].count("/0/") == 1


def test_detail_returns_breakdown(client, with_profile):
    body = client.get(f"/api/opportunities/{opp_id('German-speaking Client Associate')}/").json()
    assert body["opportunity"]["title"] == "German-speaking Client Associate"
    m = body["match"]
    assert m["eligibility"] == "blocker" and m["score"] <= 40 and m["capped"] is True
    assert {c["name"] for c in m["criteria"]} == {"Skills", "Experience", "Language", "Location", "Education", "Interests"}


def test_detail_without_profile_has_no_match(client, seeded):
    body = client.get(f"/api/opportunities/{opp_id('Programme Assistant')}/").json()
    assert body["match"] is None and body["opportunity"]["required_skills"]


def test_unknown_opportunity_returns_404(client, with_profile):
    r = client.get("/api/opportunities/99999/")
    assert r.status_code == 404 and "error" in r.json()
    assert client.post("/api/shortlist/99999/").status_code == 404


def test_shortlist_twice_does_not_duplicate_and_remove_is_idempotent(client, with_profile):
    pk = opp_id("Programme Assistant")
    assert client.post(f"/api/shortlist/{pk}/").json() == {"id": pk, "shortlisted": True}
    assert client.post(f"/api/shortlist/{pk}/").status_code == 200
    assert ShortlistItem.objects.filter(profile=with_profile).count() == 1
    assert next(r for r in client.get("/api/recommendations/").json()["results"] if r["id"] == pk)["shortlisted"]

    assert client.delete(f"/api/shortlist/{pk}/").json() == {"id": pk, "shortlisted": False}
    assert client.delete(f"/api/shortlist/{pk}/").status_code == 200
    assert ShortlistItem.objects.count() == 0


def test_shortlist_requires_profile(client, seeded):
    r = client.post(f"/api/shortlist/{opp_id('Programme Assistant')}/")
    assert r.status_code == 400


def test_shortlist_rejects_get(client, with_profile):
    assert client.get(f"/api/shortlist/{opp_id('Programme Assistant')}/").status_code == 405


def test_shortlist_page_and_remove(client, with_profile):
    pk = opp_id("Operations Coordinator")
    client.post(f"/api/shortlist/{pk}/")
    html = client.get("/shortlist/").content.decode()
    assert "Operations Coordinator" in html
    r = client.post(f"/shortlist/{pk}/remove/")
    assert r.status_code == 302 and ShortlistItem.objects.count() == 0


def test_shortlists_are_per_session(client, with_profile):
    pk = opp_id("Programme Assistant")
    client.post(f"/api/shortlist/{pk}/")
    other = Client()
    assert "Programme Assistant" not in other.get("/shortlist/").content.decode()


def test_writes_require_csrf_token(with_profile, client):
    strict = Client(enforce_csrf_checks=True)
    strict.cookies = client.cookies  # same session, no token
    assert strict.post(f"/api/shortlist/{opp_id('Programme Assistant')}/").status_code == 403


def test_profile_save_redirects_to_recommendations(client, seeded):
    data = {
        "education_level": "bachelor", "years_experience": "2", "skills": "Excel",
        "currently_enrolled_student": "unknown", "work_authorisation_status": "unknown",
        "lang-TOTAL_FORMS": "0", "lang-INITIAL_FORMS": "0", "lang-MIN_NUM_FORMS": "0", "lang-MAX_NUM_FORMS": "10",
    }
    r = client.post("/", data)
    assert r.status_code == 302 and r["Location"] == "/recommendations/"


# ---------- shortlist page uses the same cards + details panel ----------
def _initial(html):
    m = re.search(r'<script id="initial-data"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def test_shortlist_page_sends_only_saved_roles_with_rank_and_date(client, with_profile):
    saved = [opp_id("Software Engineer"), opp_id("Programme Assistant")]
    for pk in saved:
        client.post(f"/api/shortlist/{pk}/")
    html = client.get("/shortlist/").content.decode()
    data = _initial(html)
    assert data["view"] == "shortlist"
    assert {r["id"] for r in data["results"]} == set(saved)  # nothing else from the catalogue
    ranks = {r["title"]: r["rank"] for r in data["results"]}
    assert ranks["Programme Assistant"] < ranks["Software Engineer"]  # overall rank kept
    assert set(data["saved_at"]) == {str(pk) for pk in saved}
    assert data["urls"]["matches"] == "/recommendations/" and data["urls"]["detail"].count("/0/") == 1
    assert "Senior Finance Manager" not in html  # unsaved roles are not on the page at all


def test_api_only_shortlisted_filter(client, with_profile):
    pk = opp_id("Operations Coordinator")
    client.post(f"/api/shortlist/{pk}/")
    body = client.get("/api/recommendations/?only=shortlisted").json()
    assert [r["id"] for r in body["results"]] == [pk] and str(pk) in body["saved_at"]
    assert len(client.get("/api/recommendations/").json()["results"]) == 12  # unfiltered as before


def test_matches_page_cards_carry_rank(client, with_profile):
    data = _initial(client.get("/recommendations/").content.decode())
    assert data["view"] == "matches" and [r["rank"] for r in data["results"]] == list(range(1, 13))
