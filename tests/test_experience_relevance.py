"""Experience = years score x relevance (profile experience areas vs opportunity experience areas)."""

import pytest

from matching import config as match_config
from matching.criteria import experience, matching_areas
from matching.engine import match
from matching.schemas import OpportunityData, ProfileData

SWE = dict(title="Software Engineer", country="Canada", min_years_experience=2, max_years_experience=6,
           experience_areas=["software development", "software engineering"])
OPS = dict(title="Operations Coordinator", country="Canada", min_years_experience=1, max_years_experience=4,
           experience_areas=["business operations", "logistics"])


def prof(**kw):
    base = dict(years_experience=3, experience_areas=["Business operations", "Project support"])
    return ProfileData(**{**base, **kw})


def test_related_experience_counts_fully():
    r = experience(prof(), OpportunityData(**OPS))
    assert (r.score, r.status) == (1.0, "met") and "Relevant experience: business operations" in r.reason


def test_unrelated_experience_counts_a_quarter():
    r = experience(prof(), OpportunityData(**SWE))
    assert r.score == pytest.approx(0.25) and r.status == "partial"
    assert "unrelated to this role" in r.reason and "25%" in r.reason


def test_missing_profile_areas_counts_partly_and_asks_for_them():
    r = experience(prof(experience_areas=[]), OpportunityData(**SWE))
    assert r.score == pytest.approx(0.6) and r.status == "partial" and "Add your experience areas" in r.reason


def test_opportunity_without_areas_uses_years_only():
    r = experience(prof(), OpportunityData(**{**SWE, "experience_areas": []}))
    assert (r.score, r.status) == (1.0, "met") and "unrelated" not in r.reason


def test_relevance_multiplies_the_years_score():
    short = OpportunityData(**{**SWE, "min_years_experience": 4})  # 3 years: within one year short -> 0.6
    assert experience(prof(), short).score == pytest.approx(0.6 * 0.25)
    far = OpportunityData(**{**SWE, "min_years_experience": 8})  # far short -> 0.2, stays not_met
    r = experience(prof(), far)
    assert r.score == pytest.approx(0.2 * 0.25) and r.status == "not_met"


def test_unknown_years_and_no_range_unchanged():
    assert experience(prof(years_experience=None), OpportunityData(**SWE)).status == "unknown"
    no_range = OpportunityData(**{**SWE, "min_years_experience": None, "max_years_experience": None})
    assert experience(prof(), no_range).status == "not_applicable"


@pytest.mark.parametrize(
    "mine,theirs,expected",
    [
        (["Business operations"], ["operations"], ["operations"]),            # one inside the other
        (["Project support"], ["project coordination"], ["project coordination"]),  # shared word "project"
        (["Project support"], ["customer support"], []),                       # only a generic word shared
        (["Business operations"], ["software development"], []),
        (["  "], ["research"], []),
    ],
)
def test_matching_areas(mine, theirs, expected):
    assert matching_areas(mine, theirs) == expected


def test_business_profile_scores_lower_for_software_role():
    # The scenario that motivated the change: 3 years in business operations vs a software role with a 2-6 year range.
    p = prof(skills=["Excel"], preferred_countries=["Canada"])
    swe = match(p, OpportunityData(**SWE, required_skills=["Python"]))
    exp = {c.name: c for c in swe.criteria}["Experience"]
    assert exp.status == "partial" and exp.score == pytest.approx(0.25)
    related = match(p, OpportunityData(**OPS, required_skills=["Python"]))
    assert related.score > swe.score


def test_factors_from_environment(monkeypatch):
    monkeypatch.setenv("MATCH_EXPERIENCE_UNRELATED", "0")
    monkeypatch.setenv("MATCH_EXPERIENCE_UNKNOWN", "1")
    match_config.experience_factors.cache_clear()
    assert experience(prof(), OpportunityData(**SWE)).score == 0
    assert experience(prof(experience_areas=[]), OpportunityData(**SWE)).score == 1.0


@pytest.mark.parametrize("value,msg", [("x", "number from 0 to 1"), ("1.5", "from 0 to 1"), ("-0.1", "from 0 to 1")])
def test_bad_factor_rejected(value, msg):
    with pytest.raises(match_config.WeightConfigError, match=msg):
        match_config.parse_experience_factors({"MATCH_EXPERIENCE_UNRELATED": value})
