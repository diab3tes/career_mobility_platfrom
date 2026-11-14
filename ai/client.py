"""Chooses and builds the live chat model, and wraps calls with a hard timeout.

Providers (AI_PROVIDER): groq (default), cloudflare, watsonx. Credentials AND the model name come from
the environment; there is no model name in code. Live AI unlocks only when every required setting of the
chosen provider is present. Everything else in the AI layer (prompts, agent, validation, retry, cache,
limits, mock) is provider-independent.
Provider SDKs are imported lazily, so Mock mode and the test suite never touch them.
"""

import concurrent.futures
from dataclasses import dataclass
from typing import Any, Callable

from django.conf import settings



@dataclass(frozen=True)
class Provider:
    key: str
    label: str              # shown to users ("your CV text is sent to …")
    credentials: tuple[str, ...]
    model_setting: str      # the model name is a required setting too (see .env.example for suggestions)

    @property
    def required(self) -> tuple[str, ...]:
        return (*self.credentials, self.model_setting)


PROVIDERS = {
    "groq": Provider("groq", "Groq", ("GROQ_API_KEY",), "GROQ_MODEL"),
    "cloudflare": Provider("cloudflare", "Cloudflare Workers AI", ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"), "CLOUDFLARE_MODEL"),
    "watsonx": Provider("watsonx", "IBM watsonx.ai", ("WATSONX_APIKEY", "WATSONX_URL", "WATSONX_PROJECT_ID"), "WATSONX_MODEL_ID"),
}

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")


class LLMUnavailable(Exception):
    """Timeout, network, auth or quota failure. Callers fall back; the ranking is never affected."""


def provider() -> Provider | None:
    return PROVIDERS.get(getattr(settings, "AI_PROVIDER", "groq"))


def provider_label() -> str:
    p = provider()
    return p.label if p else "an unknown AI provider"


def missing_settings() -> list[str]:
    """Names of the settings still needed for Live AI (empty list = ready)."""
    p = provider()
    if p is None:
        return [f"AI_PROVIDER (unknown value {getattr(settings, 'AI_PROVIDER', '')!r}; use {', '.join(PROVIDERS)})"]
    return [name for name in p.required if not str(getattr(settings, name, "") or "").strip()]


def live_available() -> bool:
    return not missing_settings()


def model_id() -> str:
    p = provider()
    return str(getattr(settings, p.model_setting, "") or "").strip() if p else ""


def model_display() -> str:
    """What the UI shows next to live output, e.g. "Groq · openai/gpt-oss-20b"."""
    # return f"{provider_label()} ·"
    return f"{provider_label()} · {model_id()}"


def cache_scope() -> str:
    """Provider + model, so a cached answer from one model is never shown as another's."""
    p = provider()
    return f"{p.key if p else 'none'}:{model_id()}"


def call_timeout() -> float:
    """AI_CALL_TIMEOUT_SECONDS: hard limit for one call (or one whole agent run)."""
    return float(settings.AI_CALL_TIMEOUT_SECONDS)


def get_chat_model(temperature: float = 0.2, max_tokens: int = 1200):
    """Return a LangChain chat model for the configured provider. Tests replace this function."""
    p = provider()
    if p is None or not live_available():
        raise LLMUnavailable("Live AI is not configured.")
    mid = model_id()

    if p.key == "groq":
        from langchain_groq import ChatGroq

        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        effort = getattr(settings, "GROQ_REASONING_EFFORT", "")
        if effort:
            # Only for reasoning models: they spend part of max_tokens thinking, so leave room for the answer.
            kwargs.update(reasoning_effort=effort, max_tokens=max(max_tokens, 2048))
        return ChatGroq(
            model=mid,
            api_key=settings.GROQ_API_KEY,
            temperature=temperature,
            timeout=call_timeout(),
            max_retries=3,  # the SDK backs off on 429 using retry-after; free tiers limit tokens per minute
            **kwargs,
        )

    if p.key == "cloudflare":
        from langchain_cloudflare import ChatCloudflareWorkersAI

        return ChatCloudflareWorkersAI(
            model=mid,
            account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            api_token=settings.CLOUDFLARE_API_TOKEN,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=call_timeout(),
            max_retries=1,
        )

    from langchain_ibm import ChatWatsonx

    return ChatWatsonx(
        model_id=mid,
        url=settings.WATSONX_URL,
        apikey=settings.WATSONX_APIKEY,
        project_id=settings.WATSONX_PROJECT_ID,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def call_with_timeout(fn: Callable[[], Any], timeout: float | None = None) -> Any:
    """Run fn in a worker thread. Any failure (including timeout) becomes LLMUnavailable."""
    if timeout is None:
        timeout = call_timeout()
    future = _executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise LLMUnavailable(f"The AI service did not respond within {int(timeout)} seconds.") from exc
    except LLMUnavailable:
        raise
    except Exception as exc:  # network, auth, quota, SDK errors
        if _is_rate_limit(exc):
            raise LLMUnavailable("The AI provider's rate limit was reached; try again in a minute.") from exc
        raise LLMUnavailable(f"The AI service returned an error ({type(exc).__name__}).") from exc


def _is_rate_limit(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ == "RateLimitError" or getattr(exc, "status_code", None) == 429:
            return True
        exc = exc.__cause__ or exc.__context__
    return False
