from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

import json

from ai import services as ai_services
from ai import store as ai_store
from ai import client as ai_client
from ai.mode import get_mode
from matching.adapters import opportunity_to_data, profile_to_data
from matching.engine import match
from matching.explain import ELIGIBILITY_LABELS
from profiles.views import get_session_profile
from shortlist.models import ShortlistItem

from .models import Opportunity
from .services import match_json, match_one, opportunity_json, recommendations_for


def opportunity_list(request):
    qs = Opportunity.objects.all()
    country = request.GET.get("country", "").strip()
    otype = request.GET.get("type", "").strip()
    if country:
        qs = qs.filter(country=country)
    if otype in Opportunity.Type.values:
        qs = qs.filter(type=otype)
    countries = Opportunity.objects.order_by("country").values_list("country", flat=True).distinct()
    return render(
        request,
        "opportunities.html",
        {
            "opportunities": qs,
            "countries": countries,
            "types": Opportunity.Type.choices,
            "selected_country": country,
            "selected_type": otype,
            "nav": "opportunities",
        },
    )


def _shortlisted_ids(profile) -> set[int]:
    if profile is None:
        return set()
    return set(ShortlistItem.objects.filter(profile=profile).values_list("opportunity_id", flat=True))


def _rule_summary(score: int, eligibility: str, label: str) -> dict:
    return {"score": score, "eligibility": eligibility, "eligibility_label": label}


def _recommendations_payload(request, only_shortlisted: bool = False) -> dict:
    """Ranked cards and saved AI assessments for the session's profile. With only_shortlisted, just the
    saved roles (each keeps its rank in the full list) and when they were saved."""
    profile = get_session_profile(request)
    if profile is None:
        return {"has_profile": False, "results": [], "assessments": {}}
    results = recommendations_for(profile, _shortlisted_ids(profile))
    if only_shortlisted:
        results = [r for r in results if r["shortlisted"]]
    rules = {r["id"]: _rule_summary(r["score"], r["eligibility"], r["eligibility_label"]) for r in results}
    stored = {
        str(oid): ai_store.payload(row, rules[oid])
        for oid, row in ai_store.active_for(profile).items()
        if oid in rules
    }
    payload = {"has_profile": True, "results": results, "assessments": stored}
    if only_shortlisted:
        payload["saved_at"] = {
            str(oid): created.isoformat()
            for oid, created in ShortlistItem.objects.filter(profile=profile).values_list("opportunity_id", "created_at")
        }
    return payload


def island_initial(request, view: str) -> dict:
    """Initial data for the React island on the matches page (view="matches") and shortlist page ("shortlist")."""
    return {
        **_recommendations_payload(request, only_shortlisted=view == "shortlist"),
        "view": view,
        "urls": {
            "recommendations": reverse("api_recommendations"),
            "profile": reverse("profile_form"),
            "matches": reverse("recommendations"),
            "detail": reverse("api_opportunity_detail", args=[0]),
            "shortlist": reverse("api_shortlist", args=[0]),
            "ai": reverse("api_ai_assessment", args=[0]),
        },
        "ai_mode": get_mode(request),
        "ai_provider": ai_client.model_display(),
    }


@ensure_csrf_cookie
def recommendations_page(request):
    return render(request, "recommendations.html", {"initial": island_initial(request, "matches"), "nav": "recommendations"})


@require_GET
def api_recommendations(request):
    """?only=shortlisted returns just the saved roles (used by the shortlist page)."""
    return JsonResponse(_recommendations_payload(request, only_shortlisted=request.GET.get("only") == "shortlisted"))


@require_POST
def api_ai_assessment(request, pk: int):
    """One opportunity per call. The AI text is always returned next to the rule engine's label and score."""
    o = Opportunity.objects.filter(pk=pk).first()
    if o is None:
        return JsonResponse({"error": "Opportunity not found."}, status=404)
    profile = get_session_profile(request)
    if profile is None:
        return JsonResponse({"error": "Create a profile first."}, status=400)

    try:
        body = json.loads(request.body or b"{}") if request.content_type == "application/json" else {}
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)
    refresh = bool(isinstance(body, dict) and body.get("refresh"))

    p_data, o_data = profile_to_data(profile), opportunity_to_data(o)
    rule = match(p_data, o_data)
    rule_json = _rule_summary(rule.score, rule.eligibility.value, ELIGIBILITY_LABELS[rule.eligibility])

    # The saved assessment is returned unless the user asks to run it again.
    existing = None if refresh else ai_store.active_one(profile, o.pk)
    if existing is not None:
        return JsonResponse(ai_store.payload(existing, rule_json, stored=True))

    response, cached = ai_services.assess(request, p_data, o_data, rule)
    row = ai_store.save(profile, o.pk, response)
    return JsonResponse(ai_store.payload(row, rule_json, cached=cached, stored=False))


@require_GET
def api_opportunity_detail(request, pk: int):
    o = Opportunity.objects.filter(pk=pk).first()
    if o is None:
        return JsonResponse({"error": "Opportunity not found."}, status=404)
    profile = get_session_profile(request)
    payload = {"opportunity": opportunity_json(o), "match": None, "shortlisted": False}
    if profile is not None:
        payload["match"] = match_json(match_one(profile, o))
        payload["shortlisted"] = o.pk in _shortlisted_ids(profile)
    return JsonResponse(payload)
