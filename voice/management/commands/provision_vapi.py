"""CLI provisioner — stand up the Vapi assistant + tools + phone attach.

``python manage.py provision_vapi [--dry-run]``. Auto-engages dry-run when VAPI_PRIVATE_KEY is
unset, so it runs offline/in CI without live calls (records the planned writes, issues none).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from voice import provision


class Command(BaseCommand):
    help = "Provision the Nordland Vapi assistant + server tools (zero-drift reconcile)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Record planned writes without issuing them.")

    def handle(self, *args, **opts):
        report = provision.provision_all(dry_run=opts["dry_run"])
        for r in report.results:
            warn = f"  (warn: {'; '.join(r.warnings)})" if r.warnings else ""
            err = f"  ERROR: {r.error}" if r.error else ""
            self.stdout.write(f"  {r.kind:<13} {r.name:<26} {r.action:<8} {r.vapi_id or '-'}{warn}{err}")
        self.stdout.write(self.style.SUCCESS(
            f"dry_run={report.dry_run} created={report.created} patched={report.patched} "
            f"nodrift={report.nodrift} errors={report.errors}"))
        if report.error:
            self.stderr.write(self.style.ERROR(report.error))
