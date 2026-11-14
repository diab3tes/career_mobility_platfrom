"""Deterministic stand-ins for the AI features. Used in Mock mode and as the fallback when live calls fail."""

from matching.schemas import Eligibility, MatchResult
from profiles.sample import SAMPLE_PROFILE

from .schemas import AIAssessment, AssessmentResponse, ExtractedProfile, ExtractionResponse

MOCK_LABEL = "Mock AI output"
FALLBACK_NOTICE = "Live AI was unavailable, so this is mock output generated from the rule-based result. The ranking is unaffected."

STRONG_AT = 75
MODERATE_AT = 50


def mock_extracted_profile() -> ExtractedProfile:
    allowed = ExtractedProfile.model_fields.keys()
    return ExtractedProfile(**{k: v for k, v in SAMPLE_PROFILE.items() if k in allowed})


def mock_extraction(source: str = "mock", notice: str | None = None) -> ExtractionResponse:
    return ExtractionResponse(source=source, notice=notice or MOCK_LABEL, profile=mock_extracted_profile())


def _fit(result: MatchResult) -> str:
    if result.eligibility == Eligibility.BLOCKER:
        return "weak"
    if result.score >= STRONG_AT:
        return "strong"
    if result.score >= MODERATE_AT:
        return "moderate"
    return "weak"


def mock_assessment_from_rules(result: MatchResult) -> AIAssessment:
    """Restates the rule-based result in assessment form. Adds no information the rules do not hold."""
    ordered = sorted(result.criteria, key=lambda c: -c.effective_weight)
    strengths = [f"{c.name}: {c.reason}" for c in ordered if c.status == "met"][:4]
    gaps = [f"{c.name}: {c.reason}" for c in ordered if c.status in ("partial", "not_met")][:4]
    considerations = [f"{c.name}: {c.reason}" for c in ordered if c.status == "unknown"][:3]
    considerations += result.eligibility_notes[: max(0, 6 - len(considerations))]

    fit = _fit(result)
    summary = (
        f"{MOCK_LABEL}: a {fit} fit based on the rule-based score of {result.score}/100 "
        f"with {len(strengths)} criteria met and {len(gaps)} with gaps."
    )
    if result.eligibility != Eligibility.NO_STATED_CONSTRAINT:
        summary += " Stated requirements need checking; see the eligibility label."
    return AIAssessment(fit=fit, summary=summary, strengths=strengths, gaps=gaps, considerations=considerations)


def mock_assessment(result: MatchResult, source: str = "mock", notice: str | None = None) -> AssessmentResponse:
    if notice is None:
        notice = FALLBACK_NOTICE if source == "fallback" else MOCK_LABEL
    return AssessmentResponse(source=source, notice=notice, assessment=mock_assessment_from_rules(result))
