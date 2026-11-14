"""Explanation built only from CriterionResult objects and the eligibility notes."""

from pydantic import BaseModel

from .schemas import Eligibility, MatchResult

ELIGIBILITY_LABELS = {
    Eligibility.NO_STATED_CONSTRAINT: "No stated constraint",
    Eligibility.REQUIRES_VERIFICATION: "Requires verification",
    Eligibility.BLOCKER: "Stated requirement not met",
}


class Explanation(BaseModel):
    strengths: list[str]
    gaps: list[str]
    unknowns: list[str]
    eligibility_label: str
    eligibility_notes: list[str]


def explain(result: MatchResult, top: int = 3) -> Explanation:
    by_weight = sorted(result.criteria, key=lambda c: -c.effective_weight)
    strengths = [f"{c.name}: {c.reason}" for c in by_weight if c.status == "met"][:top]
    gaps = [f"{c.name}: {c.reason}" for c in by_weight if c.status in ("partial", "not_met")][:top]
    unknowns = [f"{c.name}: {c.reason}" for c in by_weight if c.status == "unknown"]
    return Explanation(
        strengths=strengths,
        gaps=gaps,
        unknowns=unknowns,
        eligibility_label=ELIGIBILITY_LABELS[result.eligibility],
        eligibility_notes=result.eligibility_notes,
    )
