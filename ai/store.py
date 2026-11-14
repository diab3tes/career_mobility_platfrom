"""Per-user persistence of AI assessments (table user_ai_assessment)."""

from django.db import transaction

from .models import UserAIAssessment
from .schemas import AssessmentResponse


def active_for(profile) -> dict[int, UserAIAssessment]:
    """Active assessments for this user, keyed by opportunity id."""
    rows = UserAIAssessment.objects.filter(user=profile, is_active=True)
    return {row.opportunity_id: row for row in rows}


def active_one(profile, opportunity_id: int) -> UserAIAssessment | None:
    return UserAIAssessment.objects.filter(user=profile, opportunity_id=opportunity_id, is_active=True).first()


@transaction.atomic
def save(profile, opportunity_id: int, response: AssessmentResponse) -> UserAIAssessment:
    """Store a new active assessment; the previous active one for the pair becomes inactive (history kept)."""
    UserAIAssessment.objects.filter(user=profile, opportunity_id=opportunity_id, is_active=True).update(is_active=False)
    return UserAIAssessment.objects.create(
        user=profile, opportunity_id=opportunity_id, assessment_data=response.model_dump(), is_active=True
    )


def deactivate_all(profile) -> int:
    """Called when the profile changes: earlier assessments described a different profile."""
    return UserAIAssessment.objects.filter(user=profile, is_active=True).update(is_active=False)


def delete_cached_for(profile) -> int:
    """Remove shared cache rows that were made from this profile's content (used by "delete my data")."""
    from matching.adapters import profile_to_data

    from .models import AIAssessmentCache
    from .services import profile_fingerprint

    deleted, _ = AIAssessmentCache.objects.filter(profile_hash=profile_fingerprint(profile_to_data(profile))).delete()
    return deleted


def payload(row: UserAIAssessment, rule: dict, *, cached: bool = False, stored: bool = True) -> dict:
    """The JSON shape the UI expects, with the rule engine's current label attached."""
    data = AssessmentResponse.model_validate(row.assessment_data).model_dump()
    return {
        "id": row.opportunity_id,
        **data,
        "cached": cached,
        "stored": stored,
        "saved_at": row.created_at.isoformat(),
        "rule": rule,
    }
