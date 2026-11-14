"""Pydantic schema for the seed file. Validated on load by the seed command."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

EducationLevel = Literal["secondary", "diploma", "bachelor", "master", "doctorate"]
LanguageLevel = Literal["basic", "conversational", "professional", "native"]
OpportunityType = Literal["job", "internship"]
VisaSponsorship = Literal["yes", "no", "unstated"]


class LanguageRequirement(BaseModel):
    language: str = Field(min_length=1)
    level: LanguageLevel
    mandatory: bool = False


class OpportunitySeed(BaseModel):
    title: str = Field(min_length=1)
    organisation: str = Field(min_length=1)
    country: str = Field(min_length=1)
    city: str = ""
    type: OpportunityType
    description: str = Field(min_length=1)
    required_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    min_years_experience: Optional[float] = Field(default=None, ge=0, le=50)
    max_years_experience: Optional[float] = Field(default=None, ge=0, le=50)
    experience_areas: list[str] = []
    education_level_required: Optional[EducationLevel] = None
    education_fields: list[str] = []
    language_requirements: list[LanguageRequirement] = []
    local_work_auth_required: bool = False
    must_be_enrolled_student: bool = False
    visa_sponsorship: VisaSponsorship = "unstated"
    interest_tags: list[str] = []

    @field_validator("required_skills", "nice_to_have_skills", "education_fields", "interest_tags", "experience_areas")
    @classmethod
    def _strip_items(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s.strip()]

    @model_validator(mode="after")
    def _check_range(self):
        lo, hi = self.min_years_experience, self.max_years_experience
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("max_years_experience cannot be below min_years_experience")
        return self


class SeedFile(BaseModel):
    opportunities: list[OpportunitySeed]
