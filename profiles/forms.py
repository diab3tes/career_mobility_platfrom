import re

from django import forms
from django.forms import BaseFormSet, formset_factory

from .models import Profile

MAX_ITEMS = 30
MAX_ITEM_LEN = 100

LEVEL_CHOICES = [
    ("basic", "Basic"),
    ("conversational", "Conversational"),
    ("professional", "Professional"),
    ("native", "Native"),
]


def parse_list(text: str) -> list[str]:
    """Split on commas/semicolons/newlines, trim, drop blanks and case-insensitive duplicates."""
    seen, out = set(), []
    for part in re.split(r"[,;\n]", text or ""):
        item = re.sub(r"\s+", " ", part).strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


class ListField(forms.CharField):
    """Free text turned into a validated list of short strings.

    `chip` names one item (e.g. "skill"). static/js/profile_form.js then turns the textarea into a tag input
    that writes "A, B, C" back into it, so parsing and validation here are the same with or without JS."""

    widget = forms.Textarea

    def __init__(self, *args, chip: str | None = None, **kwargs):
        attrs = {"rows": 2}
        if chip:
            attrs.update({"data-chips": chip, "data-max-items": str(MAX_ITEMS)})
        kwargs.setdefault("widget", forms.Textarea(attrs=attrs))
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        return ", ".join(value) if isinstance(value, list) else value

    def to_python(self, value):
        return parse_list(super().to_python(value) or "")

    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages["required"], code="required")

    def clean(self, value):
        items = self.to_python(value)
        self.validate(items)
        if len(items) > MAX_ITEMS:
            raise forms.ValidationError(f"Please list at most {MAX_ITEMS} items.")
        if any(len(i) > MAX_ITEM_LEN for i in items):
            raise forms.ValidationError(f"Each item must be at most {MAX_ITEM_LEN} characters.")
        return items


class ProfileForm(forms.Form):
    education_level = forms.ChoiceField(choices=[("", "Select…")] + list(Profile.Education.choices))
    education_field = forms.CharField(max_length=200, required=False)
    years_experience = forms.DecimalField(min_value=0, max_value=50, max_digits=4, decimal_places=1)
    experience_areas = ListField(
        required=False,
        chip="area",
        help_text="The kinds of work you have done, e.g. business operations, project support. "
        "Used to check that your years are relevant: unrelated experience counts for less.",
    )
    skills = ListField(chip="skill", help_text="At least one. Add each skill separately, e.g. Excel, reporting.")
    preferred_countries = ListField(required=False, chip="country", help_text="Where you would like to work, e.g. Germany.")
    career_interests = ListField(required=False, chip="interest", help_text="Kinds of roles you want, e.g. programme support.")
    currently_enrolled_student = forms.ChoiceField(choices=Profile.Enrolled.choices, initial="unknown")
    work_authorisation_status = forms.ChoiceField(
        choices=Profile.WorkAuthStatus.choices,
        initial="unknown",
        label="Work authorisation",
    )
    work_authorisation = ListField(
        required=False,
        chip="country",
        label="Countries you state you may work in",
        help_text="Only if you chose “I will list the countries”. We never assume this for you.",
    )

    def clean(self):
        data = super().clean()
        status = data.get("work_authorisation_status")
        countries = data.get("work_authorisation") or []
        if status == "specified" and not countries and "work_authorisation" not in self.errors:
            self.add_error("work_authorisation", "List at least one country, or choose “Not stated”.")
        if status == "unknown":
            data["work_authorisation"] = []  # ignore stray countries when the user did not specify
        return data


class LanguageForm(forms.Form):
    language = forms.CharField(max_length=60, required=False)
    level = forms.ChoiceField(choices=[("", "Level…")] + LEVEL_CHOICES, required=False)

    def clean(self):
        data = super().clean()
        lang = (data.get("language") or "").strip()
        level = data.get("level")
        if lang and not level:
            self.add_error("level", "Choose a level.")
        if level and not lang:
            self.add_error("language", "Enter the language.")
        data["language"] = lang
        return data


class BaseLanguageFormSet(BaseFormSet):
    def clean(self):
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            lang = form.cleaned_data.get("language", "").lower()
            if not lang:
                continue
            if lang in seen:
                raise forms.ValidationError(f"“{form.cleaned_data['language']}” is listed twice.")
            seen.add(lang)

    def cleaned_languages(self) -> list[dict]:
        return [
            {"language": f.cleaned_data["language"], "level": f.cleaned_data["level"]}
            for f in self.forms
            if f.cleaned_data.get("language")
        ]


# One blank row; more are added in the browser with "Add language" (up to max_num).
LanguageFormSet = formset_factory(LanguageForm, formset=BaseLanguageFormSet, extra=1, max_num=10, validate_max=True)


def profile_to_initial(profile: Profile | dict) -> dict:
    get = (lambda k: profile[k]) if isinstance(profile, dict) else (lambda k: getattr(profile, k))
    return {
        "education_level": get("education_level"),
        "education_field": get("education_field"),
        "years_experience": get("years_experience"),
        "experience_areas": get("experience_areas"),
        "skills": get("skills"),
        "preferred_countries": get("preferred_countries"),
        "career_interests": get("career_interests"),
        "currently_enrolled_student": get("currently_enrolled_student"),
        "work_authorisation_status": get("work_authorisation_status"),
        "work_authorisation": get("work_authorisation"),
    }


def languages_initial(profile: Profile | dict) -> list[dict]:
    langs = profile["languages"] if isinstance(profile, dict) else profile.languages
    return [dict(item) for item in (langs or [])]
