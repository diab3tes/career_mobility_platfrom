"""Pydantic inputs/outputs of the rule engine. No Django imports anywhere in this package."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

EDUCATION_ORDER = ["secondary", "diploma", "bachelor", "master", "doctorate"]
LANGUAGE_ORDER = ["basic", "conversational", "professional", "native"]

EducationLevel = Literal["secondary", "diploma", "bachelor", "master", "doctorate"]
LanguageLevel = Literal["basic", "conversational", "professional", "native"]
CriterionStatus = Literal["met", "partial", "not_met", "unknown", "not_applicable"]


class LanguageEntry(BaseModel):
    language: str
    level: LanguageLevel


class LanguageReq(BaseModel):
    language: str
    level: LanguageLevel
    mandatory: bool = False


class ProfileData(BaseModel):
    education_level: Optional[EducationLevel] = None
    education_field: str = ""
    years_experience: Optional[float] = Field(default=None, ge=0, le=50)
    experience_areas: list[str] = []
    skills: list[str] = []
    languages: list[LanguageEntry] = []
    preferred_countries: list[str] = []
    career_interests: list[str] = []
    currently_enrolled_student: Literal["yes", "no", "unknown"] = "unknown"
    work_authorisation: list[str] = []
    work_authorisation_status: Literal["specified", "unknown"] = "unknown"


class OpportunityData(BaseModel):
    id: Optional[int] = None
    title: str
    organisation: str = ""
    country: str
    city: str = ""
    type: Literal["job", "internship"] = "job"
    description: str = ""
    required_skills: list[str] = []
    nice_to_have_skills: list[str] = []
    min_years_experience: Optional[float] = None
    max_years_experience: Optional[float] = None
    experience_areas: list[str] = []
    education_level_required: Optional[EducationLevel] = None
    education_fields: list[str] = []
    language_requirements: list[LanguageReq] = []
    local_work_auth_required: bool = False
    must_be_enrolled_student: bool = False
    visa_sponsorship: Literal["yes", "no", "unstated"] = "unstated"
    interest_tags: list[str] = []


class Eligibility(str, Enum):
    NO_STATED_CONSTRAINT = "no_stated_constraint"
    REQUIRES_VERIFICATION = "requires_verification"
    BLOCKER = "blocker"


ELIGIBILITY_RANK = {
    Eligibility.NO_STATED_CONSTRAINT: 0,
    Eligibility.REQUIRES_VERIFICATION: 1,
    Eligibility.BLOCKER: 2,
}


class CriterionResult(BaseModel):
    name: str
    score: float = Field(ge=0, le=1)
    status: CriterionStatus
    weight: float  # nominal weight from the scoring table
    effective_weight: float = 0.0  # after rescaling to 100 (0 when not applicable)
    reason: str


class MatchResult(BaseModel):
    opportunity_id: Optional[int] = None
    title: str
    score: int = Field(ge=0, le=100)
    uncapped_score: int = Field(ge=0, le=100)
    eligibility: Eligibility
    eligibility_notes: list[str] = []
    criteria: list[CriterionResult]
