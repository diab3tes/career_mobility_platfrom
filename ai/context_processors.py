from . import client
from .mode import get_mode, live_available


def ai_mode(request):
    return {
        "ai_mode": get_mode(request),
        "ai_live_available": live_available(),
        "ai_provider_label": client.provider_label(),
        "ai_model": client.model_id(),
        "ai_missing": ", ".join(client.missing_settings()),
    }
