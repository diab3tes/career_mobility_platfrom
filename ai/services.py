"""Mode, cache, session limit and fallback around the match agent."""

import hashlib
import json
import logging

from matching.schemas import MatchResult, OpportunityData, ProfileData

from . import client, limits
from .match_agent import PROMPT_VERSION, AgentContext, AssessmentInvalid, run_agent
from .mock import mock_assessment
from .mode import LIVE, get_mode
from .models import AIAssessmentCache
from .schemas import AssessmentResponse

log = logging.getLogger(__name__)

LIMIT_NOTICE = "The live AI limit for this session has been reached, so this is mock output from the rule-based result."


def profile_fingerprint(profile: ProfileData) -> str:
    """Hash of the profile content alone; stored on cache rows so a user's deletion can find them."""
    return hashlib.sha256(json.dumps(profile.model_dump(), sort_keys=True, default=str).encode()).hexdigest()


def cache_key(profile: ProfileData, opp: OpportunityData, model_scope: str) -> str:
    payload = json.dumps(
        {"profile": profile.model_dump(), "opportunity": opp.model_dump(), "model": model_scope, "prompt": PROMPT_VERSION},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def assess(request, profile: ProfileData, opp: OpportunityData, rule_result: MatchResult) -> tuple[AssessmentResponse, bool]:
    """Return (response, cached). Never raises for AI problems: failures become source="fallback"."""
    if get_mode(request) != LIVE:
        return mock_assessment(rule_result), False

    key = cache_key(profile, opp, client.cache_scope())
    hit = AIAssessmentCache.objects.filter(key=key).first()
    if hit is not None:
        return AssessmentResponse.model_validate(hit.result), True

    if not limits.try_consume(request):
        return mock_assessment(rule_result, source="fallback", notice=LIMIT_NOTICE), False

    try:
        assessment = run_agent(AgentContext(profile=profile, opportunity=opp, rule_result=rule_result))
    except (client.LLMUnavailable, AssessmentInvalid) as exc:
        log.warning("AI assessment fell back to mock: %s", exc)
        reason = "Live AI returned output that failed validation twice." if isinstance(exc, AssessmentInvalid) else str(exc)
        notice = f"{reason} Showing mock output from the rule-based result instead; the ranking is unaffected."
        return mock_assessment(rule_result, source="fallback", notice=notice), False

    response = AssessmentResponse(source="live", model_id=client.model_display(), assessment=assessment)
    AIAssessmentCache.objects.update_or_create(
        key=key,
        defaults={"opportunity_id": opp.id, "result": response.model_dump(), "profile_hash": profile_fingerprint(profile)},
    )
    return response, False
