"""Deterministic rule-based matching: score 0-100 plus a separate eligibility label."""

import math
from typing import Iterable

from .criteria import ALL_CRITERIA
from .schemas import (
    ELIGIBILITY_RANK,
    LANGUAGE_ORDER,
    Eligibility,
    MatchResult,
    OpportunityData,
    ProfileData,
)
from .skills import normalise_country, normalise_text, normalised_set

BLOCKER_CAP = 40


def assess_eligibility(p: ProfileData, o: OpportunityData) -> tuple[Eligibility, list[str]]:
    """Separate from the score. Wording never says the user is or is not legally eligible."""
    blockers: list[str] = []
    verify: list[str] = []
    ok: list[str] = []

    if o.local_work_auth_required:
        listed = normalised_set(p.work_authorisation, normalise_country)
        if p.work_authorisation_status != "specified" or not listed:
            verify.append(
                f"This role states a local work authorisation requirement for {o.country}. "
                "You have not stated your work authorisation, so this requires verification."
            )
        elif normalise_country(o.country) in listed:
            ok.append(f"This role states a local work authorisation requirement; you stated you may work in {o.country}. Still confirm with the employer.")
        else:
            blockers.append(
                f"This role states a local work authorisation requirement for {o.country}; "
                f"the countries you stated ({', '.join(p.work_authorisation)}) do not include it."
            )

    if o.must_be_enrolled_student:
        if p.currently_enrolled_student == "unknown":
            verify.append("This role is for currently enrolled students. You have not stated your enrolment, so this requires verification.")
        elif p.currently_enrolled_student == "no":
            blockers.append("This role is for currently enrolled students; you stated you are not currently enrolled.")
        else:
            ok.append("This role is for currently enrolled students; you stated you are enrolled.")

    mine: dict[str, int] = {}
    for e in p.languages:
        k = normalise_text(e.language)
        mine[k] = max(mine.get(k, -1), LANGUAGE_ORDER.index(e.level))
    for req in o.language_requirements:
        if not req.mandatory:
            continue
        need = LANGUAGE_ORDER.index(req.level)
        have = mine.get(normalise_text(req.language))
        if not p.languages:
            verify.append(f"{req.language} ({req.level}) is mandatory. You have not listed languages, so this requires verification.")
        elif have is None:
            blockers.append(f"{req.language} ({req.level}) is mandatory; it is not in your stated languages.")
        elif need - have >= 2:
            blockers.append(f"{req.language} ({req.level}) is mandatory; you stated {LANGUAGE_ORDER[have]}.")
        elif need - have == 1:
            verify.append(f"{req.language} ({req.level}) is mandatory; you stated {LANGUAGE_ORDER[have]}, one level short. This requires verification.")

    if blockers:
        return Eligibility.BLOCKER, blockers + verify
    if verify:
        return Eligibility.REQUIRES_VERIFICATION, verify + ok
    return Eligibility.NO_STATED_CONSTRAINT, ok


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def match(p: ProfileData, o: OpportunityData) -> MatchResult:
    results = [fn(p, o) for fn in ALL_CRITERIA]

    applicable = [r for r in results if r.status != "not_applicable"]
    total_weight = sum(r.weight for r in applicable)  # 0 only if every applicable criterion is weighted 0
    for r in results:
        applies = r.status != "not_applicable" and total_weight > 0
        r.effective_weight = round(r.weight * 100 / total_weight, 4) if applies else 0.0

    raw = sum(r.score * r.effective_weight for r in results)  # already on 0-100 scale
    uncapped = max(0, min(100, _round_half_up(raw)))

    eligibility, notes = assess_eligibility(p, o)
    score = min(uncapped, BLOCKER_CAP) if eligibility == Eligibility.BLOCKER else uncapped

    return MatchResult(
        opportunity_id=o.id,
        title=o.title,
        score=score,
        uncapped_score=uncapped,
        eligibility=eligibility,
        eligibility_notes=notes,
        criteria=results,
    )


def rank(p: ProfileData, opportunities: Iterable[OpportunityData]) -> list[MatchResult]:
    """Score descending; ties by eligibility (clear, verify, blocker), then title."""
    results = [match(p, o) for o in opportunities]
    results.sort(key=lambda r: (-r.score, ELIGIBILITY_RANK[r.eligibility], r.title))
    return results
