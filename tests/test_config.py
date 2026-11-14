"""Tunables come from the environment, are range-checked, and actually take effect."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from ai import cv_extractor, limits, match_agent
from config.env import ConfigError, env_float, env_int
from matching import config as match_config
from matching.engine import match
from matching.schemas import OpportunityData, ProfileData

from .pdf_utils import CV_TEXT, make_pdf


# ---------- generic parsing ----------
def test_env_int_defaults_parses_and_rejects(monkeypatch):
    monkeypatch.delenv("X_TEST", raising=False)
    assert env_int("X_TEST", 7) == 7
    monkeypatch.setenv("X_TEST", " 12 ")
    assert env_int("X_TEST", 7, min_value=1, max_value=20) == 12
    monkeypatch.setenv("X_TEST", "abc")
    with pytest.raises(ConfigError, match="X_TEST must be a whole number"):
        env_int("X_TEST", 7)
    monkeypatch.setenv("X_TEST", "0")
    with pytest.raises(ConfigError, match="at least 1"):
        env_int("X_TEST", 7, min_value=1)
    monkeypatch.setenv("X_TEST", "2.5")
    assert env_float("X_TEST", 1.0, min_value=1, max_value=3) == 2.5


# ---------- match weights ----------
def test_weights_default_and_override():
    assert match_config.parse_weights({}) == match_config.DEFAULT_WEIGHTS
    w = match_config.parse_weights({"MATCH_WEIGHT_SKILLS": "50", "MATCH_WEIGHT_INTERESTS": "0"})
    assert w["Skills"] == 50 and w["Interests"] == 0 and w["Location"] == 15


@pytest.mark.parametrize("value,msg", [("x", "whole number"), ("101", "from 0 to 100"), ("-1", "from 0 to 100")])
def test_bad_weight_rejected(value, msg):
    with pytest.raises(match_config.WeightConfigError, match=msg):
        match_config.parse_weights({"MATCH_WEIGHT_SKILLS": value})


def test_all_zero_weights_rejected():
    env = {match_config.env_name(n): "0" for n in match_config.DEFAULT_WEIGHTS}
    with pytest.raises(match_config.WeightConfigError, match="above 0"):
        match_config.parse_weights(env)


@pytest.fixture
def reset_weights():
    match_config.weights.cache_clear()
    yield
    match_config.weights.cache_clear()


def _sample_match():
    p = ProfileData(skills=["excel"], preferred_countries=["Kenya"], years_experience=2)
    o = OpportunityData(title="R", country="Germany", required_skills=["excel"], min_years_experience=1)
    return match(p, o)


def test_env_weights_change_the_score(monkeypatch, reset_weights):
    default = _sample_match()  # skills met, experience met, location not met
    assert default.score == round(100 * (35 + 20) / (35 + 20 + 15))
    monkeypatch.setenv("MATCH_WEIGHT_LOCATION", "0")
    match_config.weights.cache_clear()
    assert _sample_match().score == 100  # location switched off
    assert {c.name: c.weight for c in _sample_match().criteria}["Location"] == 0


def test_only_zero_weighted_criteria_apply_gives_zero_not_crash(monkeypatch, reset_weights):
    for n in match_config.DEFAULT_WEIGHTS:
        monkeypatch.setenv(match_config.env_name(n), "0")
    monkeypatch.setenv("MATCH_WEIGHT_INTERESTS", "5")  # the only weighted criterion, but it won't apply below
    match_config.weights.cache_clear()
    r = match(ProfileData(skills=["x"]), OpportunityData(title="R", country="DE"))
    assert r.score == 0 and all(c.effective_weight == 0 for c in r.criteria)


# ---------- CV and AI limits (read per call from settings) ----------
def test_cv_size_limit_from_settings(settings):
    settings.CV_MAX_UPLOAD_MB = 1
    big = SimpleUploadedFile("cv.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024), content_type="application/pdf")
    with pytest.raises(cv_extractor.CVRejected, match="larger than 1 MB"):
        cv_extractor.validate_upload(big)


def test_cv_min_words_from_settings(settings):
    doc = cv_extractor.extract_text(make_pdf([CV_TEXT]))
    settings.CV_MIN_WORDS_PER_PAGE = doc.words_per_page + 1
    with pytest.raises(cv_extractor.CVRejected, match="text-based"):
        cv_extractor.check_enough_text(doc)
    settings.CV_MIN_WORDS_PER_PAGE = 10
    cv_extractor.check_enough_text(doc)


def test_cv_chars_sent_from_settings(settings):
    settings.CV_MAX_CHARS_SENT = 1234
    assert cv_extractor.max_chars_sent() == 1234


def test_session_limit_from_settings(settings, rf):
    settings.AI_LIVE_CALLS_PER_SESSION = 1
    request = rf.get("/")
    request.session = {}
    assert limits.try_consume(request) is True and limits.try_consume(request) is False


def test_agent_limits_from_settings(settings):
    from langchain.agents.middleware import ModelCallLimitMiddleware

    settings.AI_AGENT_MAX_MODEL_CALLS = 3
    captured = {}

    import ai.match_agent as ma
    real = ma.create_agent

    def spy(**kwargs):
        captured.update(kwargs)
        return object()

    ma.create_agent = spy
    try:
        ma.build_agent(llm=object(), tools=[])
    finally:
        ma.create_agent = real
    mw = [m for m in captured["middleware"] if isinstance(m, ModelCallLimitMiddleware)][0]
    assert mw.run_limit == 3


def test_timeout_from_settings(settings):
    from ai import client

    settings.AI_CALL_TIMEOUT_SECONDS = 7
    assert client.call_timeout() == 7.0


# ---------- prompt version is derived, not hand-maintained ----------
def test_prompt_version_tracks_prompt_text(monkeypatch):
    v1 = match_agent._prompt_version()
    assert v1 == match_agent.PROMPT_VERSION and v1.startswith("match-")
    monkeypatch.setattr(match_agent, "MATCH_AGENT_SYSTEM", match_agent.MATCH_AGENT_SYSTEM + "\nBe brief.")
    assert match_agent._prompt_version() != v1
