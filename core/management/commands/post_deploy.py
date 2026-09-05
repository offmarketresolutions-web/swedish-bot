"""One idempotent command chaining everything a deploy needs after code+migrate.

Runs, in order: seed_kb (no-clobber), import_general_knowledge (the repo package by
default), seed_service_areas, import_postcodes (only if PostcodeArea is empty),
selfcheck. Safe to run on every deploy — every step it calls is itself
idempotent, so re-running never clobbers owner edits or duplicates rows.

    python manage.py post_deploy
    python manage.py post_deploy --faq path/to/general_knowledge.zip
    python manage.py post_deploy --postcodes path/to/SE.zip
    python manage.py post_deploy --skip-selfcheck   # e.g. first deploy before data exists
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

# Shipped with the code (Dockerfile COPYs it), so a rebuilt container always carries the
# corpus. Before this, the FAQ import needed an operator to remember `--faq <path>` and
# there was no package to point at — which is how production ran on 1 FAQ entry.
DEFAULT_FAQ_PACKAGE = settings.BASE_DIR / "data" / "general_knowledge" / "nordland-general-knowledge.json"


class Command(BaseCommand):
    help = "Idempotent post-deploy chain: seed_kb, import_general_knowledge, seed_service_areas, import_postcodes, selfcheck."

    def add_arguments(self, parser):
        parser.add_argument("--faq", default=None,
                             help="Path to the general-knowledge FAQ package (.zip/.json). "
                                  f"Defaults to {DEFAULT_FAQ_PACKAGE.name} in the repo.")
        parser.add_argument("--skip-faq", action="store_true",
                             help="Don't import the FAQ package at all.")
        parser.add_argument("--postcodes", default=None,
                             help="Path to the GeoNames SE postcode export (.zip/.txt). "
                                  "Only imported if PostcodeArea is currently empty, "
                                  "unless --force-postcodes.")
        parser.add_argument("--force-postcodes", action="store_true",
                             help="Re-run import_postcodes even if PostcodeArea already has rows.")
        parser.add_argument("--skip-selfcheck", action="store_true",
                             help="Don't run selfcheck at the end (its own command exits 1 on FAIL).")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.MIGRATE_HEADING("1/5 seed_kb"))
        call_command("seed_kb")

        self.stdout.write(self.style.MIGRATE_HEADING("2/5 import_general_knowledge"))
        faq_path = opts["faq"]
        if opts["skip_faq"]:
            self.stdout.write("skipped (--skip-faq)")
        elif faq_path:
            path = Path(faq_path)
            if not path.exists():
                raise CommandError(f"--faq path not found: {path}")
            call_command("import_general_knowledge", str(path))
        elif DEFAULT_FAQ_PACKAGE.exists():
            call_command("import_general_knowledge", str(DEFAULT_FAQ_PACKAGE))
        else:
            self.stdout.write(f"skipped (no --faq path given and {DEFAULT_FAQ_PACKAGE} is missing)")

        self.stdout.write(self.style.MIGRATE_HEADING("3/5 seed_service_areas"))
        call_command("seed_service_areas")

        self.stdout.write(self.style.MIGRATE_HEADING("4/5 import_postcodes"))
        from crm.models import PostcodeArea
        already_loaded = PostcodeArea.objects.exists()
        postcodes_path = opts["postcodes"]
        if postcodes_path and (opts["force_postcodes"] or not already_loaded):
            path = Path(postcodes_path)
            if not path.exists():
                raise CommandError(f"--postcodes path not found: {path}")
            call_command("import_postcodes", str(path))
        elif already_loaded:
            self.stdout.write(f"skipped (PostcodeArea already has {PostcodeArea.objects.count()} rows; "
                               "pass --force-postcodes to re-import)")
        else:
            self.stdout.write("skipped (no --postcodes path given)")

        self.stdout.write(self.style.MIGRATE_HEADING("5/5 selfcheck"))
        if opts["skip_selfcheck"]:
            self.stdout.write("skipped (--skip-selfcheck)")
        else:
            call_command("selfcheck")

        self.stdout.write(self.style.SUCCESS("post_deploy complete."))
