"""Match agent + assessment endpoint. The real create_agent graph runs against a scripted fake chat model;
nothing calls a real AI provider."""

import json
from typing import Any

import pytest
from django.core.management import call_command
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from ai import client, limits, services
from ai.match_agent import AgentContext, AssessmentInvalid, check_no_legal_claims, make_tools, run_agent
from ai.models import AIAssessmentCache
from ai.schemas import AIAssessment
from matching.engine import match
from matching.schemas import OpportunityData, ProfileData
from opportunities.models import Opportunity
from profiles.models import Profile
from profiles.sample import SAMPLE_PROFILE

CREDS = dict(AI_PROVIDER="groq", GROQ_API_KEY="test-key", GROQ_MODEL="openai/gpt-oss-20b")
VALID = {
    "fit": "strong",
    "summary": "Operations and reporting experience lines up well with this role.",
    "strengths": ["Coordinated projects and reported weekly in Excel"],
    "gaps": [],
    "considerations": ["Work authorisation requires verification."],
}


class ScriptedChat(BaseChatModel):
    """Returns pre-written AIMessages in order and records what it was sent."""

    script: list[Any]
    seen: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return ChatResult(generations=[ChatGeneration(message=nxt)])


def call(name, args, cid):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": cid, "type": "tool_call"}])


def ctx(**profile_over) -> AgentContext:
    p = ProfileData(**{**SAMPLE_PROFILE, **profile_over})
    o = OpportunityData(id=7, title="Operations Coordinator", country="Singapore",
                        required_skills=["Excel", "Reporting"], local_work_auth_required=True)
    return AgentContext(profile=p, opportunity=o, rule_result=match(p, o))


@pytest.fixture
def scripted(monkeypatch):
    def install(script):
        model = ScriptedChat(script=list(script), seen=[])
        monkeypatch.setattr(client, "get_chat_model", lambda **kw: model)
        return model
    return install


# ---------- agent ----------
def test_agent_uses_tools_and_returns_validated_assessment(scripted):
    model = scripted([call("get_rule_based_result", {"opportunity_id": 7}, "c1"), call("AIAssessment", VALID, "c2")])
    a = run_agent(ctx())
    assert isinstance(a, AIAssessment) and a.fit == "strong"
    tool_msgs = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
    rule = json.loads(tool_msgs[0].content)
    assert rule["score_0_to_100"] == ctx().rule_result.score and rule["criteria"]
    assert "eligibility_label" not in rule and "eligibility_notes" not in rule  # eligibility stays with the rules


def test_get_profile_withholds_eligibility_fields():
    c = ctx(work_authorisation_status="specified", work_authorisation=["Canada"], currently_enrolled_student="no")
    get_profile, get_opportunity, get_rule = make_tools(c)
    data = json.loads(get_profile.invoke({}))
    assert "work_authorisation" not in data and "currently_enrolled_student" not in data
    assert data["skills"] == SAMPLE_PROFILE["skills"]
    assert "error" in json.loads(get_opportunity.invoke({"opportunity_id": 999}))
    opp = json.loads(get_opportunity.invoke({"opportunity_id": 7}))
    for withheld in ("local_work_auth_required", "must_be_enrolled_student", "visa_sponsorship"):
        assert withheld not in opp
    assert opp["required_skills"] == ["Excel", "Reporting"]
    assert json.loads(get_rule.invoke({"opportunity_id": 7}))["score_0_to_100"] == c.rule_result.score


def test_legal_claim_is_rejected_then_retry_succeeds(scripted):
    claim = {**VALID, "considerations": ["You are eligible to work in Singapore."]}
    model = scripted([call("AIAssessment", claim, "c1"), call("AIAssessment", VALID, "c2")])
    a = run_agent(ctx())
    assert a.considerations == VALID["considerations"]
    retry_prompt = model.seen[1][1].content  # [0] is the system prompt, [1] the retried request
    assert "rejected" in retry_prompt and "legal eligibility" in retry_prompt


def test_invalid_twice_raises(scripted):
    scripted([AIMessage(content="I think it is a good fit."), AIMessage(content="Still no tool call.")])
    with pytest.raises(AssessmentInvalid):
        run_agent(ctx())


def test_service_error_raises_llm_unavailable(scripted):
    scripted([ConnectionError("network down")])
    with pytest.raises(client.LLMUnavailable):
        run_agent(ctx())


def test_legal_claim_filter_allows_verification_wording():
    ok = AIAssessment(fit="moderate", summary="Reasonable fit.", considerations=[
        "Local work authorisation requires verification; you have not stated it.",
        "The visa position requires verification with the employer.",
    ])
    check_no_legal_claims(ok)
    for bad in ["You need a visa for this role.", "You are not eligible here.", "You are legally allowed to work."]:
        with pytest.raises(AssessmentInvalid):
            check_no_legal_claims(AIAssessment(fit="weak", summary=bad))


# ---------- endpoint ----------
@pytest.fixture
def setup(client, db):
    call_command("seed_opportunities")
    p = Profile.objects.create(**SAMPLE_PROFILE)
    s = client.session
    s["profile_id"] = p.pk
    s.save()
    return p


@pytest.fixture
def live(client, settings, setup):
    for k, v in CREDS.items():
        setattr(settings, k, v)
    s = client.session
    s["ai_mode"] = "live"
    s.save()
    return client


@pytest.fixture
def agent_spy(monkeypatch):
    calls = []

    def install(result):
        def fake(context):
            calls.append(context)
            if isinstance(result, Exception):
                raise result
            return AIAssessment(**result)
        monkeypatch.setattr(services, "run_agent", fake)
        return calls
    return install


def oid(title):
    return Opportunity.objects.get(title=title).pk


def post_ai(c, pk):
    return c.post(f"/api/opportunities/{pk}/ai-assessment/")


def test_mock_mode_returns_labelled_mock_with_rule_label(client, setup, agent_spy):
    calls = agent_spy(VALID)
    body = post_ai(client, oid("Business Analyst Intern")).json()
    assert body["source"] == "mock" and body["cached"] is False and not calls
    assert body["rule"]["eligibility"] == "requires_verification"
    assert body["assessment"]["summary"].startswith("Mock AI output")
    assert AIAssessmentCache.objects.count() == 0


def test_missing_credentials_force_mock_even_if_session_says_live(client, setup, settings, agent_spy):
    calls = agent_spy(VALID)
    s = client.session
    s["ai_mode"] = "live"
    s.save()
    settings.GROQ_API_KEY = ""
    assert post_ai(client, oid("Programme Assistant")).json()["source"] == "mock" and not calls


def test_live_success_is_cached_and_reused(live, agent_spy):
    calls = agent_spy(VALID)
    pk = oid("Programme Assistant")
    first = post_ai(live, pk).json()
    assert first["source"] == "live" and first["cached"] is False and first["model_id"] == "Groq · openai/gpt-oss-20b"
    second = post_ai(live, pk).json()  # the saved assessment comes back; nothing runs
    assert second["stored"] is True and second["assessment"] == first["assessment"]
    rerun = live.post(f"/api/opportunities/{pk}/ai-assessment/", data='{"refresh": true}', content_type="application/json").json()
    assert rerun["cached"] is True and rerun["stored"] is False  # re-run served by the shared cache
    assert len(calls) == 1 and AIAssessmentCache.objects.count() == 1
    assert live.session[limits.SESSION_KEY] == 1  # stored rows and cache hits do not use the session budget


def test_cache_key_changes_with_profile_and_model():
    c = ctx()
    k1 = services.cache_key(c.profile, c.opportunity, "m1")
    assert k1 == services.cache_key(c.profile, c.opportunity, "m1")
    assert k1 != services.cache_key(c.profile, c.opportunity, "m2")
    assert k1 != services.cache_key(ctx(years_experience=5).profile, c.opportunity, "m1")


@pytest.mark.parametrize(
    "error,text",
    [(client.LLMUnavailable("The AI service did not respond within 45 seconds."), "did not respond"),
     (AssessmentInvalid("bad"), "failed validation twice")],
)
def test_live_failure_falls_back_without_touching_ranking(live, agent_spy, error, text):
    agent_spy(error)
    before = live.get("/api/recommendations/").json()["results"]
    body = post_ai(live, oid("Programme Assistant")).json()
    assert body["source"] == "fallback" and text in body["notice"] and "ranking is unaffected" in body["notice"]
    assert body["assessment"]["fit"] in {"strong", "moderate", "weak"}
    assert AIAssessmentCache.objects.count() == 0  # failures are not cached
    assert live.get("/api/recommendations/").json()["results"] == before


def test_ai_never_changes_score_or_label(live, agent_spy):
    agent_spy({**VALID, "fit": "strong"})
    pk = oid("German-speaking Client Associate")
    body = post_ai(live, pk).json()
    assert body["assessment"]["fit"] == "strong"  # AI may disagree...
    assert body["rule"]["eligibility"] == "blocker" and body["rule"]["score"] <= 40  # ...rules are unchanged
    detail = live.get(f"/api/opportunities/{pk}/").json()["match"]
    assert detail["eligibility"] == "blocker" and detail["score"] == body["rule"]["score"]


def test_session_limit_falls_back_without_calling_agent(live, agent_spy):
    calls = agent_spy(VALID)
    s = live.session
    s[limits.SESSION_KEY] = limits.limit()
    s.save()
    body = post_ai(live, oid("Programme Assistant")).json()
    assert body["source"] == "fallback" and "limit" in body["notice"] and not calls


def test_endpoint_errors(client, setup):
    assert post_ai(client, 99999).status_code == 404
    assert client.get(f"/api/opportunities/{oid('Programme Assistant')}/ai-assessment/").status_code == 405
    s = client.session
    del s["profile_id"]
    s.save()
    assert post_ai(client, oid("Programme Assistant")).status_code == 400
