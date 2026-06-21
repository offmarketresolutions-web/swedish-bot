"""Generate AI summaries for idle sessions that don't have one yet (V2 P-E).
Runs the summary path beyond escalation so staff always have a recap. Cron it."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from crm.leads import build_summary
from crm.models import Session


class Command(BaseCommand):
    help = "Summarize idle sessions lacking an ai_summary."

    def add_arguments(self, parser):
        parser.add_argument("--idle-minutes", type=int, default=30)
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(minutes=opts["idle_minutes"])
        qs = Session.objects.filter(ai_summary="", updated_at__lt=cutoff)[: opts["limit"]]
        n = 0
        for s in qs:
            summary = build_summary(s)
            if summary:
                s.ai_summary = summary
                s.save(update_fields=["ai_summary"])
                n += 1
        self.stdout.write(self.style.SUCCESS(f"Summarized {n} idle session(s)."))
