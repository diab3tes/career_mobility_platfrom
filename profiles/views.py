from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ai import client as ai_client
from ai import limits
from ai import store as ai_store
from ai.cv_extractor import CVRejected, max_bytes, process_cv
from matching.config import total_weight, weights
from ai.mode import get_mode

from .forms import LanguageFormSet, ProfileForm, languages_initial, profile_to_initial
from .models import Profile
from .sample import SAMPLE_PROFILE

SESSION_KEY = "profile_id"
EXTRACTABLE = [
    "education_level", "education_field", "years_experience", "experience_areas",
    "skills", "preferred_countries", "career_interests",
]


def _differs(old, new) -> bool:
    from decimal import Decimal

    if isinstance(old, Decimal) or isinstance(new, Decimal):
        return Decimal(str(old)) != Decimal(str(new))
    return old != new


ACTIVITY_REFRESH = timedelta(hours=1)


def get_session_profile(request) -> Profile | None:
    pid = request.session.get(SESSION_KEY)
    profile = Profile.objects.filter(pk=pid).first() if pid else None
    if profile is not None:
        # Retention counts from the last visit. Refreshed at most hourly; .update() leaves updated_at alone.
        now = timezone.now()
        if now - profile.last_active_at > ACTIVITY_REFRESH:
            Profile.objects.filter(pk=profile.pk).update(last_active_at=now)
            profile.last_active_at = now
    return profile


@require_POST
def delete_my_data(request):
    """Delete this visitor's profile and everything derived from it, then start a fresh session."""
    profile = get_session_profile(request)
    if profile is not None:
        ai_store.delete_cached_for(profile)  # shared AI cache rows made from this profile's content
        profile.delete()  # cascades to shortlist items and saved AI assessments (user_ai_assessment)
    request.session.flush()
    messages.success(request, "Your profile, shortlist and saved AI assessments have been deleted from this server.")
    return redirect("profile_form")


def _blank_forms(existing):
    if existing is not None:
        return (
            ProfileForm(initial=profile_to_initial(existing)),
            LanguageFormSet(initial=languages_initial(existing), prefix="lang"),
        )
    return ProfileForm(), LanguageFormSet(prefix="lang")


def _render(request, form, langs, status=200, **extra):
    ctx = {
        "form": form,
        "langs": langs,
        "has_profile": get_session_profile(request) is not None,
        "nav": "profile",
        "ai_live_remaining": limits.remaining(request),
        "weights": weights(),
        "weight_total": total_weight(),
        "cv_max_mb": settings.CV_MAX_UPLOAD_MB,
        "retention_days": settings.DATA_RETENTION_DAYS,
        **extra,
    }
    return render(request, "profile_form.html", ctx, status=status)


def profile_form(request):
    existing = get_session_profile(request)

    if request.method == "POST":
        form = ProfileForm(request.POST)
        langs = LanguageFormSet(request.POST, prefix="lang")
        if form.is_valid() and langs.is_valid():
            d = form.cleaned_data
            values = {
                "education_level": d["education_level"],
                "education_field": d["education_field"].strip(),
                "years_experience": d["years_experience"],
                "experience_areas": d["experience_areas"],
                "skills": d["skills"],
                "languages": langs.cleaned_languages(),
                "preferred_countries": d["preferred_countries"],
                "career_interests": d["career_interests"],
                "currently_enrolled_student": d["currently_enrolled_student"],
                "work_authorisation": d["work_authorisation"],
                "work_authorisation_status": d["work_authorisation_status"],
            }
            if existing:
                changed = any(_differs(getattr(existing, k), v) for k, v in values.items())
                for k, v in values.items():
                    setattr(existing, k, v)
                existing.save()
                profile = existing
                if changed:
                    ai_store.deactivate_all(profile)  # earlier AI assessments described the old profile
            else:
                profile = Profile.objects.create(**values)
            request.session[SESSION_KEY] = profile.pk
            messages.success(request, "Profile saved.")
            return redirect("recommendations")
        messages.error(request, "Please fix the highlighted fields.")
        return _render(request, form, langs)

    if request.GET.get("sample"):
        messages.info(request, "Sample profile loaded. Review it and press Save to use it.")
        form = ProfileForm(initial=profile_to_initial(SAMPLE_PROFILE))
        langs = LanguageFormSet(initial=languages_initial(SAMPLE_PROFILE), prefix="lang")
        return _render(request, form, langs)

    form, langs = _blank_forms(existing)
    return _render(request, form, langs)


@require_POST
def cv_upload(request):
    """Pre-fill the form from a CV. Nothing is saved until the user submits the form."""
    upload = request.FILES.get("cv")
    mode = get_mode(request)
    try:
        # Consent: in Live mode the CV text goes to a third party, so the user must agree first.
        # Checked before anything else, so no file is read and no model is called without it.
        if mode == "live" and request.POST.get("consent") != "yes":
            raise CVRejected(
                f"Please tick the box to agree that your CV text is sent to {ai_client.provider_label()}, "
                "or fill in the form manually."
            )
        if upload is None and int(request.META.get("CONTENT_LENGTH") or 0) > max_bytes():
            raise CVRejected(f"The file is larger than {settings.CV_MAX_UPLOAD_MB} MB. Please upload a smaller PDF.")
        result = process_cv(upload, mode, allow_live_call=lambda: limits.try_consume(request))
    except CVRejected as exc:
        form, langs = _blank_forms(get_session_profile(request))
        return _render(request, form, langs, status=400, cv_error=str(exc))

    extracted = result.profile
    filled = set(extracted.filled_fields())
    initial = {k: v for k, v in extracted.model_dump().items() if k != "languages"}
    initial.update(currently_enrolled_student="unknown", work_authorisation_status="unknown", work_authorisation=[])
    form = ProfileForm(initial=initial)
    langs = LanguageFormSet(initial=[l.model_dump() for l in extracted.languages], prefix="lang")

    for name in EXTRACTABLE:
        form.fields[name].ai_state = "filled" if name in filled else "empty"
    for name in ("currently_enrolled_student", "work_authorisation_status", "work_authorisation"):
        form.fields[name].ai_state = "never"

    return _render(
        request,
        form,
        langs,
        cv_result={
            "source": result.source,
            "notice": result.notice,
            "filled_count": len(filled),
            "languages_filled": "languages" in filled,
            "model_id": result.model_id,
        },
    )
