"""Convert stored objects to engine inputs. Duck-typed on attributes: no Django import needed."""

from .schemas import OpportunityData, ProfileData


def _f(v):
    return None if v is None else float(v)


def profile_to_data(p) -> ProfileData:
    return ProfileData(
        education_level=p.education_level or None,
        education_field=p.education_field or "",
        years_experience=_f(p.years_experience),
        experience_areas=list(p.experience_areas or []),
        skills=list(p.skills or []),
        languages=list(p.languages or []),
        preferred_countries=list(p.preferred_countries or []),
        career_interests=list(p.career_interests or []),
        currently_enrolled_student=p.currently_enrolled_student,
        work_authorisation=list(p.work_authorisation or []),
        work_authorisation_status=p.work_authorisation_status,
    )


def opportunity_to_data(o) -> OpportunityData:
    return OpportunityData(
        id=o.pk,
        title=o.title,
        organisation=o.organisation,
        country=o.country,
        city=o.city,
        type=o.type,
        description=o.description,
        required_skills=list(o.required_skills or []),
        nice_to_have_skills=list(o.nice_to_have_skills or []),
        min_years_experience=_f(o.min_years_experience),
        max_years_experience=_f(o.max_years_experience),
        experience_areas=list(o.experience_areas or []),
        education_level_required=o.education_level_required or None,
        education_fields=list(o.education_fields or []),
        language_requirements=list(o.language_requirements or []),
        local_work_auth_required=o.local_work_auth_required,
        must_be_enrolled_student=o.must_be_enrolled_student,
        visa_sponsorship=o.visa_sponsorship,
        interest_tags=list(o.interest_tags or []),
    )
