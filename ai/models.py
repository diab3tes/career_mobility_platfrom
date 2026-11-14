from django.db import models
from django.db.models import Q


class AIAssessmentCache(models.Model):
    """Shared de-duplication of LLM calls. Key = hash of (profile content, opportunity content, provider+model,
    prompt version), so identical requests never pay twice. Not tied to a user."""

    key = models.CharField(max_length=64, unique=True)
    # Fingerprint of the profile content alone, so "delete my data" can remove cached answers made from it.
    profile_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    opportunity = models.ForeignKey("opportunities.Opportunity", on_delete=models.CASCADE)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class UserAIAssessment(models.Model):
    """The AI assessment a user saw for an opportunity, kept so it survives page reloads.

    The app has no accounts: the anonymous user is represented by their session Profile, so `user` points
    at profiles.Profile (column user_id). At most one row per (user, opportunity) is active; re-running
    an assessment deactivates the previous row, and editing the profile deactivates all of that user's
    rows because they were based on the old profile.
    """

    user = models.ForeignKey(
        "profiles.Profile", on_delete=models.CASCADE, db_column="user_id", related_name="ai_assessments"
    )
    opportunity = models.ForeignKey("opportunities.Opportunity", on_delete=models.CASCADE, related_name="user_ai_assessments")
    assessment_data = models.JSONField()  # AssessmentResponse: source, notice, model_id, assessment{fit, summary, ...}
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_ai_assessment"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "opportunity"], condition=Q(is_active=True), name="uniq_active_ai_assessment_per_user_opportunity"
            ),
        ]
        indexes = [models.Index(fields=["user", "is_active"], name="user_ai_assess_user_active")]

    def __str__(self) -> str:
        return f"AI assessment user={self.user_id} opportunity={self.opportunity_id} active={self.is_active}"
