import pytest
from django.core.management import call_command

from opportunities.management.commands.seed_opportunities import load_seed
from opportunities.models import Opportunity


def test_seed_file_validates_and_has_enough_entries():
    seed = load_seed()
    assert len(seed.opportunities) >= 10


@pytest.mark.django_db
def test_seed_command_is_idempotent():
    call_command("seed_opportunities")
    first = Opportunity.objects.count()
    call_command("seed_opportunities")
    assert Opportunity.objects.count() == first == 12


@pytest.mark.django_db
def test_opportunity_list_page_and_filters(client):
    call_command("seed_opportunities")
    assert client.get("/opportunities/").status_code == 200
    html = client.get("/opportunities/?country=Germany").content.decode()
    assert "Programme Assistant" in html and "Software Engineer" not in html
    html = client.get("/opportunities/?type=internship").content.decode()
    assert "Business Analyst Intern" in html and "Programme Assistant" not in html
