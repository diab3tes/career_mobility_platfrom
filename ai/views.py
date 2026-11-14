import json

from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .mode import get_mode, live_available, set_mode


def _wants_json(request) -> bool:
    return request.content_type == "application/json" or "application/json" in request.headers.get("Accept", "")


@require_POST
def api_ai_mode(request):
    """Set the Live / Mock toggle. Accepts JSON {"mode": ...} or a plain form post (no-JS fallback)."""
    if request.content_type == "application/json":
        try:
            mode = json.loads(request.body or b"{}").get("mode")
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
    else:
        mode = request.POST.get("mode")

    status, error = 200, None
    try:
        set_mode(request, mode)
    except ValueError as exc:
        status, error = 400, str(exc)
    except PermissionError as exc:
        status, error = 409, str(exc)

    if _wants_json(request):
        body = {"mode": get_mode(request), "live_available": live_available()}
        if error:
            body["error"] = error
        return JsonResponse(body, status=status)

    nxt = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/"
    return redirect(nxt)
