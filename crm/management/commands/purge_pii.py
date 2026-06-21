"""GDPR retention/erasure (V2 P-F): purge conversations + customer PII + uploaded
files older than --days. Dry-run by default; pass --yes to delete. Cron monthly."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Purge conversations + customer PII + files older than --days (GDPR)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--yes", action="store_true")

    def handle(self, *args, **opts):
        from chat.models import Conversation
        from crm.models import Customer, CustomerFile

        cutoff = timezone.now() - timedelta(days=opts["days"])
        convs = Conversation.objects.filter(started_at__lt=cutoff)
        custs = Customer.objects.filter(created_at__lt=cutoff)
        if not opts["yes"]:
            self.stdout.write(
                f"DRY RUN (cutoff {cutoff.date()}): would purge {convs.count()} conversations "
                f"+ {custs.count()} customers (+ their files). Re-run with --yes.")
            return
        for cf in CustomerFile.objects.filter(customer__in=custs):
            try:
                cf.file.delete(save=False)
            except Exception:  # noqa: BLE001
                pass
        nconv, ncust = convs.count(), custs.count()
        convs.delete()   # cascades Message + Session
        custs.delete()   # cascades CustomerFile
        self.stdout.write(self.style.SUCCESS(
            f"Purged {nconv} conversations + {ncust} customers (cutoff {cutoff.date()})."))
