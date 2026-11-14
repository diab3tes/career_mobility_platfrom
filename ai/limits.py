"""Per-session cap on live AI calls (AI_LIVE_CALLS_PER_SESSION). Free tiers cap tokens and the demo is public."""

from django.conf import settings

SESSION_KEY = "ai_live_calls"


def limit() -> int:
    return settings.AI_LIVE_CALLS_PER_SESSION


def remaining(request) -> int:
    return max(0, limit() - int(request.session.get(SESSION_KEY, 0)))


def try_consume(request) -> bool:
    """Count one live call. Returns False (and counts nothing) when the session limit is reached."""
    used = int(request.session.get(SESSION_KEY, 0))
    if used >= limit():
        return False
    request.session[SESSION_KEY] = used + 1
    return True
