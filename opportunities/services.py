"""Glue between stored models and the pure matching engine, plus JSON serialisers."""

from matching.adapters import opportunity_to_data, profile_to_data
from matching.engine import match, rank
from matching.explain import ELIGIBILITY_LABELS, explain
from matching.schemas import MatchResult

from .models import Opportunity


def opportunity_json(o: Opportunity) -> dict:
    return {
        "id": o.pk,
        "title": o.title,
        "organisation": o.organisation,
        "country": o.country,
        "city": o.city,
        "type": o.type,
        "type_label": o.get_type_display(),
        "description": o.description,
        "required_skills": o.required_skills,
        "nice_to_have_skills": o.nice_to_have_skills,
        "min_years_experience": None if o.min_years_experience is None else float(o.min_years_experience),
        "max_years_experience": None if o.max_years_experience is None else float(o.max_years_experience),
        "experience_areas": o.experience_areas,
        "education_level_required": o.education_level_required,
        "education_fields": o.education_fields,
        "language_requirements": o.language_requirements,
        "local_work_auth_required": o.local_work_auth_required,
        "must_be_enrolled_student": o.must_be_enrolled_student,
        "visa_sponsorship": o.visa_sponsorship,
        "visa_sponsorship_label": o.get_visa_sponsorship_display(),
        "interest_tags": o.interest_tags,
    }


def match_json(result: MatchResult) -> dict:
    exp = explain(result)
    return {
        "score": result.score,
        "uncapped_score": result.uncapped_score,
        "capped": result.score != result.uncapped_score,
        "eligibility": result.eligibility.value,
        "eligibility_label": ELIGIBILITY_LABELS[result.eligibility],
        "eligibility_notes": result.eligibility_notes,
        "strengths": exp.strengths,
        "gaps": exp.gaps,
        "unknowns": exp.unknowns,
        "criteria": [
            {
                **c.model_dump(),
                "points": round(c.score * c.effective_weight, 1),
            }
            for c in result.criteria
        ],
    }


def card_json(o: Opportunity, result: MatchResult, shortlisted: set[int]) -> dict:
    return {
        "id": o.pk,
        "title": o.title,
        "organisation": o.organisation,
        "country": o.country,
        "city": o.city,
        "type_label": o.get_type_display(),
        **match_json(result),
        "shortlisted": o.pk in shortlisted,
    }


def recommendations_for(profile, shortlisted: set[int]) -> list[dict]:
    opps = {o.pk: o for o in Opportunity.objects.all()}
    ranked = rank(profile_to_data(profile), [opportunity_to_data(o) for o in opps.values()])
    return [{**card_json(opps[r.opportunity_id], r, shortlisted), "rank": i} for i, r in enumerate(ranked, start=1)]


def match_one(profile, o: Opportunity) -> MatchResult:
    return match(profile_to_data(profile), opportunity_to_data(o))
