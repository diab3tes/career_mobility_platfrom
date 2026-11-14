import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from pydantic import ValidationError

from opportunities.models import Opportunity
from opportunities.schemas import SeedFile

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "opportunities.json"


def load_seed(path: Path = DEFAULT_PATH) -> SeedFile:
    """Parse and validate the seed file. Raises pydantic.ValidationError on bad data."""
    return SeedFile.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


class Command(BaseCommand):
    help = "Load (or refresh) the fictional opportunities from opportunities/data/opportunities.json"

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(DEFAULT_PATH))

    def handle(self, *args, **opts):
        try:
            seed = load_seed(Path(opts["path"]))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read seed file: {exc}")
        except ValidationError as exc:
            raise CommandError(f"Seed file failed validation:\n{exc}")

        created = updated = 0
        for item in seed.opportunities:
            data = item.model_dump()
            _, was_created = Opportunity.objects.update_or_create(
                title=data.pop("title"), organisation=data.pop("organisation"), defaults=data
            )
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} new, {updated} updated opportunities."))
