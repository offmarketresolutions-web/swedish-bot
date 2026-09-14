"""Record, per manual, whether it documents what alarm/error codes mean.

Until a manual has been scanned the bot behaves exactly as before, so this is
safe to run incrementally. Re-run after loading or replacing manuals; documents
whose bytes haven't changed since their last scan are skipped.

    manage.py scan_alarm_codes                # everything not yet scanned
    manage.py scan_alarm_codes --rescan       # including already-scanned ones
    manage.py scan_alarm_codes --machine AirX # substring filter on the model name
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from kb.alarms import scan_and_save
from kb.models import MachineDocument


class Command(BaseCommand):
    help = "Scan machine manuals for alarm/error-code documentation."

    def add_arguments(self, parser):
        parser.add_argument("--rescan", action="store_true",
                            help="Re-scan documents whose bytes are unchanged too.")
        parser.add_argument("--machine", default="",
                            help="Only machines whose model name contains this.")
        parser.add_argument("--pace", type=float, default=2.0,
                            help="Seconds to wait between manuals (rate limits).")

    def handle(self, *args, **opts):
        docs = MachineDocument.objects.select_related("machine").exclude(pdf="").order_by("pk")
        if opts["machine"]:
            docs = docs.filter(machine__model_name__icontains=opts["machine"])
        docs = list(docs)
        done = skipped = failed = 0
        for doc in docs:
            fresh = doc.alarm_scan_sha and doc.alarm_scan_sha == (doc.sha256 or "")
            if fresh and not opts["rescan"]:
                skipped += 1
                continue
            try:
                documents_codes, codes = scan_and_save(doc)
            except Exception as exc:  # noqa: BLE001 — one bad manual must not end the run
                failed += 1
                self.stderr.write(f"  {doc.machine}: {type(exc).__name__}: {str(exc)[:120]}")
                continue
            done += 1
            shown = ", ".join(codes[:8]) + ("…" if len(codes) > 8 else "")
            self.stdout.write(f"  {doc.machine!s:34} "
                              + (f"codes: {shown}" if documents_codes else "NO CODES DOCUMENTED"))
            if opts["pace"]:
                time.sleep(opts["pace"])
        self.stdout.write(self.style.SUCCESS(
            f"scanned {done}, skipped {skipped} (already current), failed {failed}"))
