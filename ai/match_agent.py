"""AI match assessment: a LangChain agent (create_agent) giving a qualitative second opinion.

The agent reads data only through three tools bound to one profile/opportunity pair. Its output is
validated with Pydantic and checked for legal-eligibility claims. It never changes the score, the rank
or the eligibility label.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from django.conf import settings
from pydantic import ValidationError

from matching.schemas import MatchResult, OpportunityData, ProfileData

from . import client
from .prompts import MATCH_AGENT_SYSTEM
from .schemas import AIAssessment


# Eligibility inputs are never sent to the model. The rule engine owns eligibility and the UI shows its
# label beside every AI answer, so the model has no reason (and no data) to discuss work rights or visas.
PROFILE_FIELDS_WITHHELD = {"work_authorisation", "work_authorisation_status", "currently_enrolled_student"}
OPPORTUNITY_FIELDS_WITHHELD = {"local_work_auth_required", "must_be_enrolled_student", "visa_sponsorship"}

_LEGAL = re.compile(
    r"\b(eligib\w*|ineligib\w*|visas?|work permits?|right to work|work rights?|"
    r"authori[sz]ed to work|legally|citizenship|residen(cy|ce) permit)\b",
    re.IGNORECASE,
)


class AssessmentInvalid(Exception):
    pass


@dataclass
class AgentContext:
    profile: ProfileData
    opportunity: OpportunityData
    rule_result: MatchResult

    def profile_json(self) -> dict:
        return self.profile.model_dump(exclude=PROFILE_FIELDS_WITHHELD)

    def opportunity_json(self) -> dict:
        return self.opportunity.model_dump(exclude=OPPORTUNITY_FIELDS_WITHHELD)

    def rule_json(self) -> dict:
        r = self.rule_result
        return {
            "score_0_to_100": r.score,
            "criteria": [
                {"name": c.name, "status": c.status, "reason": c.reason}
                for c in r.criteria
                if c.status != "not_applicable"
            ],
        }


def _j(data) -> str:
    """Compact JSON keeps tool output small (free tiers count tokens per minute)."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def make_tools(ctx: AgentContext):
    oid = ctx.opportunity.id

    def _wrong(opportunity_id: int) -> str | None:
        if opportunity_id != oid:
            return json.dumps({"error": f"Only opportunity {oid} is available in this assessment."})
        return None

    @tool
    def get_profile() -> str:
        """Return the candidate's career profile as JSON (education, experience, skills, languages, preferences)."""
        return _j(ctx.profile_json())

    @tool
    def get_opportunity(opportunity_id: int) -> str:
        """Return the opportunity's details and requirements as JSON."""
        return _wrong(opportunity_id) or _j(ctx.opportunity_json())

    @tool
    def get_rule_based_result(opportunity_id: int) -> str:
        """Return the deterministic rule-based match result (score and per-criterion statuses with reasons)."""
        return _wrong(opportunity_id) or _j(ctx.rule_json())

    return [get_profile, get_opportunity, get_rule_based_result]


def build_agent(llm, tools):
    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=MATCH_AGENT_SYSTEM,
        response_format=ToolStrategy(AIAssessment),
        middleware=[ModelCallLimitMiddleware(run_limit=settings.AI_AGENT_MAX_MODEL_CALLS, exit_behavior="end")],
    )


def check_no_legal_claims(a: AIAssessment) -> None:
    """Reject text that talks about legal eligibility, visas or work rights unless it defers to verification."""
    for text in [a.summary, *a.strengths, *a.gaps, *a.considerations]:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if _LEGAL.search(sentence) and "verif" not in sentence.lower():
                raise AssessmentInvalid(
                    f"Statement about legal eligibility, visas or work rights is not allowed: {sentence[:120]!r}. "
                    "Say only that such matters require verification."
                )


def _validate(result) -> AIAssessment:
    raw = result.get("structured_response") if isinstance(result, dict) else None
    if raw is None:
        raise AssessmentInvalid("No structured assessment was returned. Finish by calling the AIAssessment tool.")
    try:
        a = raw if isinstance(raw, AIAssessment) else AIAssessment.model_validate(
            raw.model_dump() if hasattr(raw, "model_dump") else raw
        )
    except ValidationError as exc:
        errs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
        raise AssessmentInvalid(f"Invalid assessment: {errs}") from exc
    check_no_legal_claims(a)
    return a


def run_agent(ctx: AgentContext) -> AIAssessment:
    """Run the agent; retry once with the validation error. Raises AssessmentInvalid or LLMUnavailable."""
    llm = client.get_chat_model(temperature=0.1, max_tokens=900)
    agent = build_agent(llm, make_tools(ctx))
    request = f"Assess opportunity {ctx.opportunity.id} for this candidate. Use the tools, then return your assessment."
    messages = [HumanMessage(request)]
    last: Exception | None = None
    for _ in range(2):
        try:
            result = client.call_with_timeout(
                lambda: agent.invoke({"messages": messages}, config={"recursion_limit": settings.AI_AGENT_RECURSION_LIMIT})
            )
            return _validate(result)
        except client.LLMUnavailable as exc:
            cause = exc.__cause__
            if cause is not None and type(cause).__name__ == "GraphRecursionError":
                last = AssessmentInvalid("The assessment took too many steps.")
            else:
                raise
        except AssessmentInvalid as exc:
            last = exc
        messages = [HumanMessage(f"{request}\n\nYour previous answer was rejected: {last}")]
    raise last  # type: ignore[misc]


def _prompt_version() -> str:
    """Fingerprint of everything that shapes the model's answer: system prompt, tool descriptions, output schema
    and the withheld fields. It changes exactly when one of them changes, so stale cached answers are never
    reused, and there is no version string to remember to bump."""
    # A dummy context: only the tools' names and descriptions are read here; they are never called.
    dummy = AgentContext(profile=ProfileData(), opportunity=OpportunityData(id=0, title="-", country="-"), rule_result=None)
    tools = make_tools(dummy)
    parts = [
        MATCH_AGENT_SYSTEM,
        json.dumps(AIAssessment.model_json_schema(), sort_keys=True),
        json.dumps(sorted(PROFILE_FIELDS_WITHHELD | OPPORTUNITY_FIELDS_WITHHELD)),
        *[f"{t.name}:{t.description}" for t in tools],
    ]
    return "match-" + hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


PROMPT_VERSION = _prompt_version()
