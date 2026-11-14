from django.db import models


class ShortlistItem(models.Model):
    profile = models.ForeignKey("profiles.Profile", on_delete=models.CASCADE, related_name="shortlist")
    opportunity = models.ForeignKey("opportunities.Opportunity", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "opportunity"], name="uniq_shortlist_pair"),
        ]
