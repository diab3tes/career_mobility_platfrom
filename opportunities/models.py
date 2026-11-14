from django.db import models


class Opportunity(models.Model):
    class Type(models.TextChoices):
        JOB = "job", "Job"
        INTERNSHIP = "internship", "Internship"

    class Visa(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"
        UNSTATED = "unstated", "Not stated"

    title = models.CharField(max_length=200)
    organisation = models.CharField(max_length=200)
    country = models.CharField(max_length=100)
    city = models.CharField(max_length=100, blank=True)
    type = models.CharField(max_length=20, choices=Type.choices)
    description = models.TextField()
    required_skills = models.JSONField(default=list, blank=True)
    nice_to_have_skills = models.JSONField(default=list, blank=True)
    min_years_experience = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    max_years_experience = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    # Kinds of work the experience should be in; makes the Experience rule weigh years by relevance.
    experience_areas = models.JSONField(default=list, blank=True)
    education_level_required = models.CharField(max_length=20, null=True, blank=True)
    education_fields = models.JSONField(default=list, blank=True)
    language_requirements = models.JSONField(default=list, blank=True)  # [{language, level, mandatory}]
    local_work_auth_required = models.BooleanField(default=False)
    must_be_enrolled_student = models.BooleanField(default=False)
    visa_sponsorship = models.CharField(max_length=10, choices=Visa.choices, default=Visa.UNSTATED)
    interest_tags = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["title", "organisation"], name="uniq_opportunity_title_org"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.organisation}, {self.country})"
