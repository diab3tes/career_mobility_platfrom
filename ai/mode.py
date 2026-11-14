"""Live / Mock AI mode, stored in the session. Mock is the default and the only option without provider keys."""

from . import client

SESSION_KEY = "ai_mode"
LIVE, MOCK = "live", "mock"
MODES = (LIVE, MOCK)


def live_available() -> bool:
    return client.live_available()


def get_mode(request) -> str:
    """The effective mode. A stale "live" in the session is ignored once keys are gone."""
    if not live_available():
        return MOCK
    return LIVE if request.session.get(SESSION_KEY) == LIVE else MOCK


def set_mode(request, mode: str) -> str:
    if mode not in MODES:
        raise ValueError("mode must be 'live' or 'mock'")
    if mode == LIVE and not live_available():
        raise PermissionError(f"Live AI is unavailable: set {', '.join(client.missing_settings())} in the server environment.")
    request.session[SESSION_KEY] = mode
    return mode
