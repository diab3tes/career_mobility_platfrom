"""Provider switch. Credentials and the model name both come from settings; there is no model default in code.
Models are only constructed, never invoked: no network."""

import pytest

from ai import client

PROVIDERS = [
    ("groq", {"GROQ_API_KEY": "k", "GROQ_MODEL": "some-groq-model"}),
    ("cloudflare", {"CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_MODEL": "@cf/some/model"}),
    ("watsonx", {"WATSONX_APIKEY": "k", "WATSONX_URL": "https://x.invalid", "WATSONX_PROJECT_ID": "p", "WATSONX_MODEL_ID": "some/model"}),
]


@pytest.mark.parametrize("provider,values", PROVIDERS)
def test_each_provider_needs_every_setting_including_the_model(settings, provider, values):
    settings.AI_PROVIDER = provider
    assert client.live_available() is False
    assert client.missing_settings() == list(values)  # model name listed as required
    names = list(values)
    for name in names[:-1]:
        setattr(settings, name, values[name])
    assert client.missing_settings() == [names[-1]] and client.live_available() is False
    setattr(settings, names[-1], values[names[-1]])
    assert client.live_available() is True and client.missing_settings() == []
    model_name = values[client.provider().model_setting]
    assert client.model_id() == model_name
    assert client.cache_scope() == f"{provider}:{model_name}"


def test_no_model_default_in_code(settings):
    settings.GROQ_API_KEY = "k"  # key alone is not enough
    assert client.model_id() == ""
    assert client.missing_settings() == ["GROQ_MODEL"]
    with pytest.raises(client.LLMUnavailable):
        client.get_chat_model()


def test_blank_model_counts_as_missing(settings):
    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "   "
    assert client.missing_settings() == ["GROQ_MODEL"]


def test_unknown_provider_is_reported(settings):
    settings.AI_PROVIDER = "openai"
    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "m"
    assert client.live_available() is False and client.model_id() == ""
    assert "unknown value 'openai'" in client.missing_settings()[0]


def test_model_display(settings):
    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "llama-3.1-8b-instant"
    assert client.model_display() == "Groq · llama-3.1-8b-instant"


def test_groq_reasoning_effort_comes_from_settings(settings):
    from langchain_groq import ChatGroq

    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "openai/gpt-oss-20b"
    settings.GROQ_REASONING_EFFORT = "low"
    llm = client.get_chat_model(temperature=0.1, max_tokens=900)
    assert isinstance(llm, ChatGroq)
    assert llm.model_name == "openai/gpt-oss-20b" and llm.temperature == 0.1
    assert llm.reasoning_effort == "low" and llm.max_tokens >= 2048


def test_groq_without_reasoning_effort_sends_none(settings):
    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "llama-3.1-8b-instant"
    llm = client.get_chat_model(max_tokens=900)
    assert llm.model_name == "llama-3.1-8b-instant" and llm.max_tokens == 900 and llm.reasoning_effort is None


def test_cloudflare_model_is_built_from_settings(settings):
    from langchain_cloudflare import ChatCloudflareWorkersAI

    settings.AI_PROVIDER = "cloudflare"
    settings.CLOUDFLARE_ACCOUNT_ID = "acc"
    settings.CLOUDFLARE_API_TOKEN = "tok"
    settings.CLOUDFLARE_MODEL = "@cf/ibm-granite/granite-4.0-h-micro"
    llm = client.get_chat_model(temperature=0.0, max_tokens=700)
    assert isinstance(llm, ChatCloudflareWorkersAI)
    assert llm.model == "@cf/ibm-granite/granite-4.0-h-micro" and llm.account_id == "acc"


@pytest.mark.django_db
def test_privacy_notice_names_the_configured_provider_and_model(client, settings):
    settings.GROQ_API_KEY = "k"
    settings.GROQ_MODEL = "openai/gpt-oss-20b"
    s = client.session
    s["ai_mode"] = "live"
    s.save()
    html = client.get("/").content.decode()
    assert "sent to Groq (openai/gpt-oss-20b)" in html and "watsonx" not in html


@pytest.mark.django_db
def test_lock_message_lists_missing_settings(client, settings):
    html = client.get("/").content.decode()
    assert "Locked to Mock" in html and "GROQ_API_KEY, GROQ_MODEL" in html
    settings.GROQ_API_KEY = "k"
    assert "Live AI needs GROQ_MODEL" in client.get("/").content.decode()
