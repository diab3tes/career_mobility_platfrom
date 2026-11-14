import json
from pathlib import Path

import pytest

from matching import criteria as C
from matching.engine import BLOCKER_CAP, match, rank
from matching.explain import explain
from matching.schemas import Eligibility, OpportunityData, ProfileData

SEED = Path(__file__).resolve().parents[1] / "opportunities" / "data" / "opportunities.json"

SAMPLE = dict(
    education_level="bachelor",
    education_field="Business Administration",
    years_experience=2,
    experience_areas=["business operations", "project support"],
    skills=["Excel", "research", "stakeholder communication", "reporting", "project coordination"],
    languages=[{"language": "Bengali", "level": "native"}, {"language": "English", "level": "professional"}],
    preferred_countries=["Germany", "Canada", "Singapore"],
    career_interests=["programme support", "business operations", "project coordination"],
)


def prof(**kw) -> ProfileData:
    return ProfileData(**{**SAMPLE, **kw})


def opp(**kw) -> OpportunityData:
    base = dict(title="Role", country="Germany")
    return OpportunityData(**{**base, **kw})


def seed_opps() -> list[OpportunityData]:
    raw = json.loads(SEED.read_text(encoding="utf-8"))["opportunities"]
    return [OpportunityData(id=i + 1, **o) for i, o in enumerate(raw)]


# ---------- skills ----------
def test_skills_full_partial_none():
    p = prof(skills=["MS Excel", " Reporting "])
    assert C.skills(p, opp(required_skills=["excel", "reporting"])).status == "met"
    r = C.skills(p, opp(required_skills=["excel", "sql"]))
    assert r.status == "partial" and r.score == 0.5 and "sql" in r.reason.lower()
    assert C.skills(p, opp(required_skills=["python"])).status == "not_met"


def test_skills_nice_to_have_bonus_is_capped():
    p = prof(skills=["excel", "sql"])
    r = C.skills(p, opp(required_skills=["excel", "python"], nice_to_have_skills=["sql"]))
    assert r.score == pytest.approx(0.5 + 0.1)
    full = C.skills(p, opp(required_skills=["excel"], nice_to_have_skills=["sql"]))
    assert full.score == 1.0


def test_skills_synonym_normalisation():
    assert C.skills(prof(skills=["Microsoft Excel"]), opp(required_skills=["excel"])).status == "met"


# ---------- experience (boundaries) ----------
@pytest.mark.parametrize(
    "years,expected_score,status",
    [(1, 1.0, "met"), (4, 1.0, "met"), (0.5, 0.6, "partial"), (0, 0.6, "partial"), (4.5, 0.7, "partial")],
)
def test_experience_boundaries_min1_max4(years, expected_score, status):
    r = C.experience(prof(years_experience=years), opp(min_years_experience=1, max_years_experience=4))
    assert (r.score, r.status) == (expected_score, status)


def test_experience_far_below_minimum():
    r = C.experience(prof(years_experience=2), opp(min_years_experience=4))
    assert r.score == 0.2 and r.status == "not_met"
    assert C.experience(prof(years_experience=3), opp(min_years_experience=4)).score == 0.6  # exactly one below


# ---------- language ----------
def test_language_levels():
    req = lambda lvl: opp(language_requirements=[{"language": "English", "level": lvl}])
    assert C.language(prof(), req("professional")).score == 1.0
    assert C.language(prof(), req("native")).score == 0.5
    assert C.language(prof(languages=[{"language": "English", "level": "basic"}]), req("professional")).score == 0.0
    assert C.language(prof(), opp(language_requirements=[{"language": "German", "level": "basic"}])).score == 0.0


def test_language_averages_requirements():
    o = opp(language_requirements=[{"language": "English", "level": "professional"}, {"language": "German", "level": "basic"}])
    r = C.language(prof(), o)
    assert r.score == 0.5 and r.status == "partial"


# ---------- location ----------
def test_location():
    assert C.location(prof(), opp(country="canada")).score == 1.0
    assert C.location(prof(), opp(country="Kenya")).status == "not_met"
    assert C.location(prof(preferred_countries=["UAE"]), opp(country="United Arab Emirates")).score == 1.0


# ---------- education ----------
def test_education_level_and_field():
    o = opp(education_level_required="bachelor", education_fields=["Business Administration"])
    assert C.education(prof(), o).score == 1.0
    assert C.education(prof(education_field="Physics"), o).score == 0.6
    assert C.education(prof(education_field=""), o).score == 0.6
    assert C.education(prof(), opp(education_level_required="bachelor")).score == 1.0  # no field specified
    assert C.education(prof(education_level="master", education_field="Physics"), o).score == 0.6


def test_education_level_short():
    assert C.education(prof(), opp(education_level_required="master")).score == 0.2
    assert C.education(prof(), opp(education_level_required="doctorate")).score == 0.0


# ---------- interests ----------
def test_interests():
    assert C.interests(prof(), opp(interest_tags=["Programme Support", "project coordination"])).score == 1.0
    assert C.interests(prof(), opp(interest_tags=["programme support", "finance"])).score == 0.5
    assert C.interests(prof(), opp(interest_tags=["finance"])).status == "not_met"


# ---------- missing data ----------
def test_not_applicable_is_dropped_and_rescaled():
    o = opp(required_skills=["excel"], country="Germany")  # only skills + location applicable
    m = match(prof(), o)
    by = {c.name: c for c in m.criteria}
    assert by["Experience"].status == "not_applicable" and by["Experience"].effective_weight == 0
    assert sum(c.effective_weight for c in m.criteria) == pytest.approx(100)
    assert by["Skills"].effective_weight == pytest.approx(35 * 100 / 50)
    assert m.score == 100


def test_unknown_profile_data_scores_zero_and_is_not_not_met():
    p = ProfileData(skills=["excel"], preferred_countries=["Germany"])
    o = opp(
        required_skills=["excel"],
        language_requirements=[{"language": "English", "level": "basic"}],
        min_years_experience=1,
        education_level_required="bachelor",
        interest_tags=["finance"],
    )
    by = {c.name: c for c in match(p, o).criteria}
    for name in ("Language", "Experience", "Education", "Interests"):
        assert by[name].status == "unknown" and by[name].score == 0
    assert "Add your languages" in by["Language"].reason


# ---------- eligibility ----------
def test_unknown_work_auth_requires_verification_never_satisfied():
    m = match(prof(), opp(local_work_auth_required=True))
    assert m.eligibility == Eligibility.REQUIRES_VERIFICATION
    assert m.score == m.uncapped_score  # no cap


def test_work_auth_specified_excluding_country_is_blocker_and_capped():
    p = prof(work_authorisation_status="specified", work_authorisation=["Canada"])
    m = match(p, opp(local_work_auth_required=True, country="Singapore", required_skills=["excel"]))
    assert m.eligibility == Eligibility.BLOCKER
    assert m.uncapped_score > BLOCKER_CAP and m.score == BLOCKER_CAP


def test_work_auth_specified_including_country_has_no_constraint():
    p = prof(work_authorisation_status="specified", work_authorisation=["Germany"])
    assert match(p, opp(local_work_auth_required=True)).eligibility == Eligibility.NO_STATED_CONSTRAINT


def test_enrolled_student_cases():
    o = opp(must_be_enrolled_student=True)
    assert match(prof(), o).eligibility == Eligibility.REQUIRES_VERIFICATION
    assert match(prof(currently_enrolled_student="no"), o).eligibility == Eligibility.BLOCKER
    assert match(prof(currently_enrolled_student="yes"), o).eligibility == Eligibility.NO_STATED_CONSTRAINT


def test_mandatory_language_cases():
    german = lambda: opp(language_requirements=[{"language": "German", "level": "professional", "mandatory": True}])
    assert match(prof(), german()).eligibility == Eligibility.BLOCKER  # absent
    far = prof(languages=[{"language": "German", "level": "basic"}])
    assert match(far, german()).eligibility == Eligibility.BLOCKER
    near = prof(languages=[{"language": "German", "level": "conversational"}])
    assert match(near, german()).eligibility == Eligibility.REQUIRES_VERIFICATION
    assert match(prof(languages=[]), german()).eligibility == Eligibility.REQUIRES_VERIFICATION
    ok = prof(languages=[{"language": "German", "level": "native"}])
    assert match(ok, german()).eligibility == Eligibility.NO_STATED_CONSTRAINT


def test_non_mandatory_language_gap_is_not_a_constraint():
    o = opp(language_requirements=[{"language": "German", "level": "professional", "mandatory": False}])
    assert match(prof(), o).eligibility == Eligibility.NO_STATED_CONSTRAINT


def test_eligibility_wording_never_claims_legal_status():
    for o in seed_opps():
        m = match(prof(), o)
        text = " ".join(m.eligibility_notes).lower()
        assert "legally" not in text and "ineligible" not in text and "not eligible" not in text


# ---------- ranking on the sample profile ----------
def test_sample_profile_ranking():
    ranked = rank(prof(), seed_opps())
    order = [r.opportunity_id for r in ranked]
    assert set(order[:3]) == {1, 2, 3}
    by = {r.opportunity_id: r for r in ranked}
    assert by[11].eligibility == Eligibility.REQUIRES_VERIFICATION
    assert by[12].eligibility == Eligibility.BLOCKER and by[12].score <= BLOCKER_CAP
    bottom_half = order[len(order) // 2:]
    assert 9 in bottom_half and 10 in bottom_half


def test_ranking_tie_break_by_eligibility_then_title():
    a = opp(title="B role")
    b = opp(title="A role", must_be_enrolled_student=True)  # verification, same score
    c = opp(title="C role")
    assert [r.title for r in rank(prof(), [b, a, c])] == ["B role", "C role", "A role"]


def test_determinism():
    p, os_ = prof(), seed_opps()
    first = [r.model_dump() for r in rank(p, os_)]
    second = [r.model_dump() for r in rank(p, list(reversed(os_)))]
    assert first == second


def test_score_is_whole_number_in_range():
    for r in rank(prof(), seed_opps()):
        assert isinstance(r.score, int) and 0 <= r.score <= 100


# ---------- explanation ----------
def test_explanation_only_uses_criterion_results():
    m = match(ProfileData(skills=["excel"], preferred_countries=["Kenya"]), seed_opps()[3])
    e = explain(m)
    reasons = {f"{c.name}: {c.reason}" for c in m.criteria}
    for line in e.strengths + e.gaps + e.unknowns:
        assert line in reasons
    assert any(line.startswith("Language") for line in e.unknowns)
    # No languages listed + mandatory English => verification, not a blocker.
    assert e.eligibility_label == "Requires verification"
