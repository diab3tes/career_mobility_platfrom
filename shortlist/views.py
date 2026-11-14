from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from opportunities.models import Opportunity
from opportunities.services import match_json, match_one
from opportunities.views import island_initial
from profiles.views import get_session_profile

from .models import ShortlistItem


@require_http_methods(["POST", "DELETE"])
def api_shortlist(request, pk: int):
    """POST adds, DELETE removes. Both are idempotent."""
    o = Opportunity.objects.filter(pk=pk).first()
    if o is None:
        return JsonResponse({"error": "Opportunity not found."}, status=404)
    profile = get_session_profile(request)
    if profile is None:
        return JsonResponse({"error": "Create a profile before shortlisting."}, status=400)

    if request.method == "POST":
        ShortlistItem.objects.get_or_create(profile=profile, opportunity=o)
        return JsonResponse({"id": o.pk, "shortlisted": True})
    ShortlistItem.objects.filter(profile=profile, opportunity=o).delete()
    return JsonResponse({"id": o.pk, "shortlisted": False})


@ensure_csrf_cookie
def shortlist_page(request):
    """React island in shortlist mode (cards + details panel). The server-rendered rows are the fallback
    shown until React starts, and for visitors without JavaScript."""
    profile = get_session_profile(request)
    rows = []
    if profile is not None:
        for item in ShortlistItem.objects.filter(profile=profile).select_related("opportunity"):
            rows.append({"item": item, "o": item.opportunity, "match": match_json(match_one(profile, item.opportunity))})
    return render(
        request,
        "shortlist.html",
        {"rows": rows, "has_profile": profile is not None, "nav": "shortlist", "initial": island_initial(request, "shortlist")},
    )


@require_POST
def shortlist_remove(request, pk: int):
    profile = get_session_profile(request)
    if profile is not None:
        ShortlistItem.objects.filter(profile=profile, opportunity_id=pk).delete()
        messages.success(request, "Removed from your shortlist.")
    return redirect("shortlist")
