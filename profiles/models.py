from django.db import models
from django.utils import timezone


class Profile(models.Model):
    """One profile per anonymous session (no accounts in this prototype)."""

    class Education(models.TextChoices):
        SECONDARY = "secondary", "Secondary school"
        DIPLOMA = "diploma", "Diploma"
        BACHELOR = "bachelor", "Bachelor's degree"
        MASTER = "master", "Master's degree"
        DOCTORATE = "doctorate", "Doctorate"

    class Enrolled(models.TextChoices):
        UNKNOWN = "unknown", "Prefer not to say"
        YES = "yes", "Yes"
        NO = "no", "No"

    class WorkAuthStatus(models.TextChoices):
        UNKNOWN = "unknown", "Not stated"
        SPECIFIED = "specified", "I will list the countries"

    education_level = models.CharField(max_length=20, choices=Education.choices)
    education_field = models.CharField(max_length=200, blank=True)
    years_experience = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    experience_areas = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list)
    languages = models.JSONField(default=list, blank=True)  # [{language, level}]
    preferred_countries = models.JSONField(default=list, blank=True)
    career_interests = models.JSONField(default=list, blank=True)
    currently_enrolled_student = models.CharField(
        max_length=10, choices=Enrolled.choices, default=Enrolled.UNKNOWN
    )
    work_authorisation = models.JSONField(default=list, blank=True)
    work_authorisation_status = models.CharField(
        max_length=10, choices=WorkAuthStatus.choices, default=WorkAuthStatus.UNKNOWN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Last time the visitor used the app (refreshed at most hourly). Retention is measured from here,
    # so purge_expired_data never removes someone who is still using the site.
    last_active_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self) -> str:
        return f"Profile #{self.pk}"
