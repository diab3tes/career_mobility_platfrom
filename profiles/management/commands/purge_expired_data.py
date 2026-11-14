"""Delete data that has not been used for DATA_RETENTION_DAYS (default 30). Run daily, e.g. by cron or
Windows Task Scheduler:   python manage.py purge_expired_data

Removes:
  * profiles not visited within the period, with their shortlist items and saved AI assessments (cascade);
  * inactive (superseded) saved AI assessments older than the period, for profiles that remain;
  * shared AI cache rows older than the period;
  * expired Django sessions.
Opportunities (the seeded catalogue) are never touched.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ai.models import AIAssessmentCache, UserAIAssessment
from profiles.models import Profile
from shortlist.models import ShortlistItem


class Command(BaseCommand):
    help = "Delete profiles, AI assessments, cached AI results and sessions older than DATA_RETENTION_DAYS."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Override DATA_RETENTION_DAYS for this run.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be deleted, delete nothing.")

    def handle(self, *args, days=None, dry_run=False, **opts):
        days = days if days is not None else settings.DATA_RETENTION_DAYS
        if days < 1:
            self.stderr.write("--days must be at least 1.")
            return
        cutoff = timezone.now() - timedelta(days=days)

        old_profiles = Profile.objects.filter(last_active_at__lt=cutoff)
        counts = {
            "profiles": old_profiles.count(),
            "shortlist items": ShortlistItem.objects.filter(profile__in=old_profiles).count(),
            "AI assessments of those profiles": UserAIAssessment.objects.filter(user__in=old_profiles).count(),
            "old inactive AI assessments": UserAIAssessment.objects.filter(is_active=False, created_at__lt=cutoff)
            .exclude(user__in=old_profiles).count(),
            "cached AI results": AIAssessmentCache.objects.filter(created_at__lt=cutoff).count(),
            "expired sessions": Session.objects.filter(expire_date__lt=timezone.now()).count(),
        }

        if not dry_run:
            with transaction.atomic():
                UserAIAssessment.objects.filter(is_active=False, created_at__lt=cutoff).exclude(user__in=old_profiles).delete()
                old_profiles.delete()  # cascades to shortlist items and the profiles' AI assessments
                AIAssessmentCache.objects.filter(created_at__lt=cutoff).delete()
                Session.objects.filter(expire_date__lt=timezone.now()).delete()

        verb = "Would delete" if dry_run else "Deleted"
        summary = ", ".join(f"{n} {label}" for label, n in counts.items())
        self.stdout.write(self.style.SUCCESS(f"{verb} (older than {days} days): {summary}."))
