import pytest

from profiles.models import Profile

pytestmark = pytest.mark.django_db


def valid_post(**over):
    data = {
        "education_level": "bachelor",
        "education_field": "Business Administration",
        "years_experience": "2",
        "experience_areas": "business operations, project support",
        "skills": "Excel, reporting, excel",
        "preferred_countries": "Germany, Canada",
        "career_interests": "programme support",
        "currently_enrolled_student": "unknown",
        "work_authorisation_status": "unknown",
        "work_authorisation": "",
        "lang-TOTAL_FORMS": "2",
        "lang-INITIAL_FORMS": "0",
        "lang-MIN_NUM_FORMS": "0",
        "lang-MAX_NUM_FORMS": "10",
        "lang-0-language": "English",
        "lang-0-level": "professional",
        "lang-1-language": "",
        "lang-1-level": "",
    }
    data.update(over)
    return data


def test_valid_profile_is_saved_and_bound_to_session(client):
    r = client.post("/", valid_post())
    assert r.status_code == 302
    p = Profile.objects.get()
    assert client.session["profile_id"] == p.pk
    assert p.skills == ["Excel", "reporting"]  # trimmed, case-insensitive dedupe
    assert p.languages == [{"language": "English", "level": "professional"}]
    assert p.work_authorisation_status == "unknown" and p.currently_enrolled_student == "unknown"


def test_resubmitting_updates_instead_of_duplicating(client):
    client.post("/", valid_post())
    client.post("/", valid_post(years_experience="5"))
    assert Profile.objects.count() == 1
    assert float(Profile.objects.get().years_experience) == 5


@pytest.mark.parametrize(
    "over,field",
    [
        ({"skills": ""}, "skills"),
        ({"skills": " , ; "}, "skills"),
        ({"education_level": ""}, "education_level"),
        ({"education_level": "wizard"}, "education_level"),
        ({"years_experience": "51"}, "years_experience"),
        ({"years_experience": "-1"}, "years_experience"),
        ({"years_experience": "abc"}, "years_experience"),
        ({"work_authorisation_status": "specified", "work_authorisation": ""}, "work_authorisation"),
        ({"skills": ", ".join(f"s{i}" for i in range(31))}, "skills"),
    ],
)
def test_invalid_profile_rejected_with_field_error(client, over, field):
    r = client.post("/", valid_post(**over))
    assert r.status_code == 200
    assert field in r.context["form"].errors
    assert Profile.objects.count() == 0
    assert "profile_id" not in client.session


def test_language_without_level_and_duplicates_rejected(client):
    r = client.post("/", valid_post(**{"lang-0-level": ""}))
    assert r.status_code == 200 and r.context["langs"].errors[0].get("level")
    r = client.post(
        "/",
        valid_post(**{"lang-TOTAL_FORMS": "2", "lang-1-language": "english", "lang-1-level": "basic"}),
    )
    assert r.status_code == 200 and "listed twice" in str(r.context["langs"].non_form_errors())


def test_specified_work_authorisation_is_stored_and_unknown_clears_countries(client):
    client.post("/", valid_post(work_authorisation_status="specified", work_authorisation="Canada"))
    assert Profile.objects.get().work_authorisation == ["Canada"]
    client.post("/", valid_post(work_authorisation_status="unknown", work_authorisation="Canada"))
    assert Profile.objects.get().work_authorisation == []


def test_sample_button_prefills_without_saving(client):
    r = client.get("/?sample=1")
    html = r.content.decode()
    assert r.status_code == 200
    assert "Business Administration" in html and "Bengali" in html and "Germany, Canada, Singapore" in html
    assert Profile.objects.count() == 0


def test_saved_profile_prefills_form(client):
    client.post("/", valid_post())
    assert "business operations" in client.get("/").content.decode()


# ---------- dynamic form (rows added in the browser, skills as chips) ----------
def _langs(*pairs):
    data = {"lang-TOTAL_FORMS": str(len(pairs)), "lang-INITIAL_FORMS": "0", "lang-MIN_NUM_FORMS": "0", "lang-MAX_NUM_FORMS": "10"}
    for i, (lang, level) in enumerate(pairs):
        data[f"lang-{i}-language"] = lang
        data[f"lang-{i}-level"] = level
    return data


def test_rows_added_in_browser_are_saved(client):
    post = valid_post(**_langs(("English", "professional"), ("Bengali", "native"), ("German", "basic"), ("French", "basic")))
    assert client.post("/", post).status_code == 302
    assert [l["language"] for l in Profile.objects.get().languages] == ["English", "Bengali", "German", "French"]


def test_more_than_ten_language_rows_rejected(client):
    rows = [(f"Lang{i}", "basic") for i in range(11)]
    r = client.post("/", valid_post(**_langs(*rows)))
    assert r.status_code == 200 and Profile.objects.count() == 0


def test_page_has_language_template_and_skill_chip_hook(client):
    html = client.get("/").content.decode()
    assert 'id="lang-template"' in html and "lang-__prefix__-language" in html
    assert 'id="add-lang"' in html and 'data-max="10"' in html
    for noun in ("skill", "area", "country", "interest"):
        assert f'data-chips="{noun}"' in html
    assert html.count('data-chips="country"') == 2  # preferred countries + work authorisation countries
    assert html.count('data-max-items="30"') == 5   # every list field
    assert "js/profile_form.js" in html


def test_skills_from_chip_input_parse_as_before(client):
    # The chip input writes "A, B, C" into the original field, so the server parses it unchanged.
    client.post("/", valid_post(skills="Excel, Power BI, Excel ,  SQL"))
    assert Profile.objects.get().skills == ["Excel", "Power BI", "SQL"]
