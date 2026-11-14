"""One function per scored criterion. Each returns a CriterionResult with nominal weight.

Rules shared by all criteria:
  * the opportunity states no requirement  -> status "not_applicable" (dropped and rescaled by the engine)
  * the profile lacks the data to judge     -> status "unknown", score 0, reason says what to add
"""

import re

from .schemas import (
    EDUCATION_ORDER,
    LANGUAGE_ORDER,
    CriterionResult,
    OpportunityData,
    ProfileData,
)
from .config import experience_factors, weights
from .skills import normalise_country, normalise_skill, normalise_text, normalised_set


NICE_TO_HAVE_BONUS = 0.1
_STOP = {"and", "of", "in", "the", "studies", "a", "for"}


def _result(name, score, status, reason) -> CriterionResult:
    return CriterionResult(name=name, score=max(0.0, min(1.0, score)), status=status, weight=weights()[name], reason=reason)


def _na(name, reason) -> CriterionResult:
    return _result(name, 0.0, "not_applicable", reason)


def _unknown(name, reason) -> CriterionResult:
    return _result(name, 0.0, "unknown", reason)


def _fmt(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:g}"


def skills(p: ProfileData, o: OpportunityData) -> CriterionResult:
    name = "Skills"
    required = normalised_set(o.required_skills)
    if not required:
        return _na(name, "This opportunity lists no required skills.")
    have = normalised_set(p.skills)
    if not have:
        return _unknown(name, "Add your skills to assess this.")

    matched = [required[k] for k in required if k in have]
    missing = [required[k] for k in required if k not in have]
    base = len(matched) / len(required)

    nice = normalised_set(o.nice_to_have_skills)
    nice_matched = [nice[k] for k in nice if k in have]
    bonus = NICE_TO_HAVE_BONUS * len(nice_matched) / len(nice) if nice else 0.0
    score = min(1.0, base + bonus)

    status = "met" if not missing else ("partial" if matched else "not_met")
    parts = [f"You match {len(matched)} of {len(required)} required skills"]
    if matched:
        parts.append(f"({', '.join(matched)})")
    text = " ".join(parts) + "."
    if missing:
        text += f" Missing: {', '.join(missing)}."
    if nice_matched:
        text += f" Bonus for nice-to-have: {', '.join(nice_matched)}."
    return _result(name, score, status, text)


# Words too generic to make two experience areas "related" on their own ("project support" vs "customer support").
_GENERIC_AREA_WORDS = {"support", "management", "services", "service", "general", "work", "team"}


def _area_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", normalise_text(text)) if t not in _STOP and t not in _GENERIC_AREA_WORDS and len(t) > 2}


def matching_areas(profile_areas: list[str], opportunity_areas: list[str]) -> list[str]:
    """Opportunity areas that the profile's experience areas cover (same phrase, one inside the other, or a
    shared meaningful word, e.g. "business operations" ~ "operations")."""
    mine = [(normalise_text(a), _area_tokens(a)) for a in profile_areas if a.strip()]
    hits = []
    for area in opportunity_areas:
        na, ta = normalise_text(area), _area_tokens(area)
        if any(m == na or (m and (m in na or na in m)) or (tm & ta) for m, tm in mine):
            hits.append(area)
    return hits


def _years(p: ProfileData, o: OpportunityData) -> tuple[float, str, str]:
    """Years against the requested range: (score, status, reason). Unchanged from the original rule."""
    lo, hi, y = o.min_years_experience, o.max_years_experience, p.years_experience
    if lo is not None and y < lo:
        if lo - y <= 1:
            return 0.6, "partial", f"You stated {_fmt(y)} years; {_fmt(lo)}+ requested (within one year of the minimum)."
        return 0.2, "not_met", f"You stated {_fmt(y)} years; {_fmt(lo)}+ requested."
    if hi is not None and y > hi:
        return 0.7, "partial", f"You stated {_fmt(y)} years, above the usual range of up to {_fmt(hi)} (may be overqualified)."
    return 1.0, "met", f"You stated {_fmt(y)} years, within the requested range."


def experience(p: ProfileData, o: OpportunityData) -> CriterionResult:
    """Experience = years score x relevance (see matching/config.py for the relevance factors)."""
    name = "Experience"
    if o.min_years_experience is None and o.max_years_experience is None:
        return _na(name, "This opportunity states no experience range.")
    if p.years_experience is None:
        return _unknown(name, "Add your years of experience to assess this.")

    years_score, years_status, reason = _years(p, o)
    if not o.experience_areas:  # nothing to compare against: years only, as before
        return _result(name, years_score, years_status, reason)

    factors = experience_factors()
    if not any(a.strip() for a in p.experience_areas):
        relevance = factors["unknown"]
        reason += f" Add your experience areas to check they are relevant; counted at {relevance:.0%} until then."
        status = "partial" if years_status == "met" else years_status
        return _result(name, years_score * relevance, status, reason)

    hits = matching_areas(p.experience_areas, o.experience_areas)
    if hits:
        return _result(name, years_score, years_status, reason + f" Relevant experience: {', '.join(hits)}.")

    relevance = factors["unrelated"]
    reason += (
        f" But your experience ({', '.join(p.experience_areas)}) is unrelated to this role "
        f"({', '.join(o.experience_areas)}), so it counts at {relevance:.0%}."
    )
    status = "partial" if years_status == "met" else years_status
    return _result(name, years_score * relevance, status, reason)


def language(p: ProfileData, o: OpportunityData) -> CriterionResult:
    name = "Language"
    if not o.language_requirements:
        return _na(name, "This opportunity states no language requirements.")
    if not p.languages:
        return _unknown(name, "Add your languages to assess this.")

    mine: dict[str, int] = {}
    for entry in p.languages:
        key = normalise_text(entry.language)
        mine[key] = max(mine.get(key, -1), LANGUAGE_ORDER.index(entry.level))

    scores, notes = [], []
    for req in o.language_requirements:
        need = LANGUAGE_ORDER.index(req.level)
        have = mine.get(normalise_text(req.language))
        tag = " (mandatory)" if req.mandatory else ""
        if have is None:
            s, note = 0.0, f"{req.language} {req.level}{tag}: not in your profile"
        elif have >= need:
            s, note = 1.0, f"{req.language} {req.level}{tag}: met"
        elif need - have == 1:
            s, note = 0.5, f"{req.language} {req.level}{tag}: one level short ({LANGUAGE_ORDER[have]})"
        else:
            s, note = 0.0, f"{req.language} {req.level}{tag}: well below ({LANGUAGE_ORDER[have]})"
        scores.append(s)
        notes.append(note)

    score = sum(scores) / len(scores)
    status = "met" if all(s == 1.0 for s in scores) else ("not_met" if score == 0 else "partial")
    return _result(name, score, status, "; ".join(notes) + ".")


def location(p: ProfileData, o: OpportunityData) -> CriterionResult:
    name = "Location"
    prefs = normalised_set(p.preferred_countries, normalise_country)
    if not prefs:
        return _unknown(name, "Add your preferred countries to assess this.")
    if normalise_country(o.country) in prefs:
        return _result(name, 1.0, "met", f"{o.country} is one of your preferred countries.")
    return _result(name, 0.0, "not_met", f"{o.country} is not among your preferred countries.")


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", normalise_text(text)) if t not in _STOP and len(t) > 2}


def _field_relevant(profile_field: str, fields: list[str]) -> bool:
    mine = _tokens(profile_field)
    pf = normalise_text(profile_field)
    for f in fields:
        nf = normalise_text(f)
        if pf and (pf in nf or nf in pf):
            return True
        if mine & _tokens(f):
            return True
    return False


def education(p: ProfileData, o: OpportunityData) -> CriterionResult:
    name = "Education"
    if o.education_level_required is None:
        return _na(name, "This opportunity states no education requirement.")
    if p.education_level is None:
        return _unknown(name, "Add your education level to assess this.")

    need = EDUCATION_ORDER.index(o.education_level_required)
    have = EDUCATION_ORDER.index(p.education_level)
    if have < need:
        s = 0.2 if need - have == 1 else 0.0
        return _result(name, s, "not_met", f"{o.education_level_required.title()} level requested; you stated {p.education_level}.")

    if not o.education_fields:
        return _result(name, 1.0, "met", f"Education level met ({o.education_level_required} requested; no specific field).")
    if not p.education_field.strip():
        return _result(name, 0.6, "partial", "Level met. Add your field of study to check relevance to the requested fields.")
    if _field_relevant(p.education_field, o.education_fields):
        return _result(name, 1.0, "met", f"Level met and your field ({p.education_field}) is relevant.")
    return _result(name, 0.6, "partial", f"Level met, but your field ({p.education_field}) is not among: {', '.join(o.education_fields)}.")


def interests(p: ProfileData, o: OpportunityData) -> CriterionResult:
    name = "Interests"
    tags = normalised_set(o.interest_tags, normalise_text)
    if not tags:
        return _na(name, "This opportunity lists no interest tags.")
    mine = normalised_set(p.career_interests, normalise_text)
    if not mine:
        return _unknown(name, "Add your career interests to assess this.")
    hits = [tags[k] for k in tags if k in mine]
    score = len(hits) / len(tags)
    status = "met" if len(hits) == len(tags) else ("partial" if hits else "not_met")
    text = f"Overlap with your interests: {', '.join(hits)}." if hits else "No overlap with your stated career interests."
    return _result(name, score, status, text)


ALL_CRITERIA = [skills, experience, language, location, education, interests]
