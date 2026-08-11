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
        from crm.models import Customer, CustomerFile, ServiceRequest, UnrevokedExternalCopy

        cutoff = timezone.now() - timedelta(days=opts["days"])
        convs = Conversation.objects.filter(started_at__lt=cutoff)
        custs = Customer.objects.filter(created_at__lt=cutoff)
        # Files mirrored to Google Drive (crm/file_sink.py) have no delete/revoke
        # contract in the n8n workflow — purging the local blob does NOT remove the
        # external copy. Must never be silently reported as "gone".
        mirrored_files = CustomerFile.objects.filter(
            customer__in=custs).exclude(drive_url="")
        n_unrevoked = mirrored_files.count()
        # Session.customer is SET_NULL, so a ServiceRequest whose conversation is
        # newer than `cutoff` survives custs.delete() below — but its payload_json
        # is a point-in-time snapshot that still embeds the customer's
        # name/phone/email/address forever unless scrubbed here too.
        srs_to_scrub = ServiceRequest.objects.filter(session__customer__in=custs)
        nscrub = 0
        for sr in srs_to_scrub:
            if sr.payload_json.get("customer"):
                sr.payload_json["customer"] = {k: "" for k in sr.payload_json["customer"]}
                if not opts["yes"]:
                    continue
                sr.save(update_fields=["payload_json"])
                nscrub += 1
        if not opts["yes"]:
            self.stdout.write(
                f"DRY RUN (cutoff {cutoff.date()}): would purge {convs.count()} conversations "
                f"+ {custs.count()} customers (+ their files), scrub {srs_to_scrub.count()} "
                f"surviving service-request payloads. {n_unrevoked} file(s) were mirrored to "
                f"Google Drive and CANNOT be revoked by this command — their external copies "
                f"would remain. Re-run with --yes.")
            return
        # Record what we cannot revoke BEFORE deleting the rows that know about it.
        for cf in mirrored_files:
            UnrevokedExternalCopy.objects.create(drive_url=cf.drive_url, file_kind=cf.kind)
        for cf in CustomerFile.objects.filter(customer__in=custs):
            try:
                cf.file.delete(save=False)
            except Exception:  # noqa: BLE001
                pass
        nconv, ncust = convs.count(), custs.count()
        convs.delete()   # cascades Message + Session (+ ServiceRequest/LeadDelivery)
        custs.delete()   # cascades CustomerFile
        self.stdout.write(self.style.SUCCESS(
            f"Purged {nconv} conversations + {ncust} customers (cutoff {cutoff.date()}); "
            f"scrubbed {nscrub} surviving service-request payloads."))
        if n_unrevoked:
            self.stdout.write(self.style.WARNING(
                f"{n_unrevoked} customer file(s) had a Google Drive mirror that could NOT be "
                f"revoked (no delete contract in the n8n integration) — external copies REMAIN "
                f"in Drive. Recorded in crm.UnrevokedExternalCopy for staff to delete by hand."))
