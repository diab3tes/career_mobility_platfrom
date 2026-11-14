import pytest

from matching import config as match_config

PROVIDER_KEYS = (
    "GROQ_API_KEY", "GROQ_MODEL", "GROQ_REASONING_EFFORT",
    "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_MODEL",
    "WATSONX_APIKEY", "WATSONX_URL", "WATSONX_PROJECT_ID", "WATSONX_MODEL_ID",
)

# The code defaults. Tests run against these whatever a developer's .env says.
TUNING_DEFAULTS = {
    "AI_LIVE_CALLS_PER_SESSION": 25,
    "AI_CALL_TIMEOUT_SECONDS": 45.0,
    "AI_AGENT_MAX_MODEL_CALLS": 6,
    "AI_AGENT_RECURSION_LIMIT": 24,
    "CV_MAX_UPLOAD_MB": 10,
    "CV_MIN_WORDS_PER_PAGE": 50,
    "CV_MAX_CHARS_SENT": 15_000,
    "DATA_RETENTION_DAYS": 30,
}


@pytest.fixture(autouse=True)
def _isolated_config(settings, monkeypatch):
    """Tests never depend on the developer's .env:
    - real AI keys never reach the suite (no test calls a real AI service; Live tests set fake keys);
    - tuning values and match weights are the code defaults (tests that need others set them)."""
    settings.AI_PROVIDER = "groq"
    for name in PROVIDER_KEYS:
        setattr(settings, name, "")
    for name, value in TUNING_DEFAULTS.items():
        setattr(settings, name, value)
    for name in match_config.DEFAULT_WEIGHTS:
        monkeypatch.delenv(match_config.env_name(name), raising=False)
    for var in match_config.EXPERIENCE_FACTOR_VARS.values():
        monkeypatch.delenv(var, raising=False)
    match_config.weights.cache_clear()
    match_config.experience_factors.cache_clear()
    yield
    match_config.weights.cache_clear()
    match_config.experience_factors.cache_clear()
