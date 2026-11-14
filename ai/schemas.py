"""Pydantic schemas for every AI output. Anything a model returns is validated against these."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Source = Literal["live", "mock", "fallback"]


def _clean_list(v: list[str], max_items: int = 30, max_len: int = 100) -> list[str]:
    seen, out = set(), []
    for item in v or []:
        s = " ".join(str(item).split())[:max_len]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:max_items]


class ExtractedLanguage(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    level: Literal["basic", "conversational", "professional", "native"]


class ExtractedProfile(BaseModel):
    """What the CV extractor may fill. Work authorisation and enrolment are deliberately absent:
    they are never inferred from a CV."""

    education_level: Optional[Literal["secondary", "diploma", "bachelor", "master", "doctorate"]] = None
    education_field: str = Field(default="", max_length=200)
    years_experience: Optional[float] = Field(default=None, ge=0, le=50)
    experience_areas: list[str] = []
    skills: list[str] = []
    languages: list[ExtractedLanguage] = []
    preferred_countries: list[str] = []
    career_interests: list[str] = []

    @field_validator("experience_areas", "skills", "preferred_countries", "career_interests")
    @classmethod
    def _lists(cls, v):
        return _clean_list(v)

    def filled_fields(self) -> list[str]:
        return [name for name, value in self.model_dump().items() if value not in (None, "", [])]


class AIAssessment(BaseModel):
    fit: Literal["strong", "moderate", "weak"]
    summary: str = Field(min_length=1, max_length=800)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    gaps: list[str] = Field(default_factory=list, max_length=6)
    considerations: list[str] = Field(default_factory=list, max_length=6)


class AssessmentResponse(BaseModel):
    source: Source
    notice: Optional[str] = None
    model_id: Optional[str] = None
    assessment: AIAssessment


class ExtractionResponse(BaseModel):
    source: Source
    notice: Optional[str] = None
    model_id: Optional[str] = None
    profile: ExtractedProfile
