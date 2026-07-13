"""Load the repo-root manual .txt files into the RUNTIME knowledge base (Sprint
S1 — old standing item, see docs/plans/2026-07-12-audit-current-state.md §7).

These raw-text manuals (geo_troubleshooting.txt, vent_content.txt, ...) have
until now only been used as mocked fixtures inside
tests/test_scenarios/conftest.py — this command creates the equivalent Machine
+ MachineDocument rows for real, so the specialist can actually load them via
chat/context.machine_pdf_context (no PDF required — MachineDocument.pdf has no
DB-level NOT NULL constraint; FileField blank enforcement is form/validation
-only, so a doc can be saved with parsed_text and no file).

Idempotent: Machine is looked up by (vendor, model_name); each source file is
deduped by sha256 (mirrors kb/management/commands/import_kb.py) so re-running
never duplicates a MachineDocument.

    python manage.py load_root_manuals [--source-dir <repo root>] [--dry-run]
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand

from config.settings import BASE_DIR

# vendor / model / category / files (repo-root .txt, utf-8) for each product
# line the 2026-07-12 test-plan scenario catalog references by name but that
# seed_kb.py's minimal catalog doesn't carry (mirrors
# tests/test_scenarios/conftest.py's `seeded` fixture — same 3 machines).
MACHINES = [
    {
        "vendor": "IVT", "model_name": "Geo 412C", "category_slug": "water_to_water",
        "slug": "geo-412c", "aliases": ["geo412c", "geo 412c", "412c"],
        "files": ["geo_troubleshooting.txt", "geo_perceivable_errors.txt"],
    },
    {
        "vendor": "IVT", "model_name": "Vent 402", "category_slug": "exhaust_air",
        "slug": "ivt-vent-402", "aliases": ["vent402", "vent 402"],
        "files": ["vent_content.txt", "vent_maintenance_full.txt"],
    },
    {
        "vendor": "Bosch", "model_name": "Greenline HE", "category_slug": "water_to_water",
        "slug": "greenline-he", "aliases": ["greenline", "greenline he", "greenline hec-e"],
        "files": ["greenline_content.txt"],
    },
]


class Command(BaseCommand):
    help = "Load the repo-root manual .txt files into Machine/MachineDocument (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--source-dir", default=str(BASE_DIR))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from kb.models import Category, Machine, MachineDocument, Vendor

        src = Path(opts["source_dir"])
        dry = opts["dry_run"]
        n_machines = n_docs = n_skipped_docs = n_missing_files = 0

        for spec in MACHINES:
            cat = Category.objects.filter(slug=spec["category_slug"]).first()
            if cat is None:
                self.stderr.write(self.style.ERROR(
                    f"Category {spec['category_slug']!r} not seeded — skipping {spec['model_name']} "
                    f"(run `manage.py seed_kb` first)."))
                continue

            if dry:
                self.stdout.write(f"[machine] {spec['vendor']} {spec['model_name']} "
                                  f"({spec['category_slug']}) <- {len(spec['files'])} file(s)")
            else:
                vendor, _ = Vendor.objects.get_or_create(
                    slug=spec["vendor"].lower(), defaults={"name": spec["vendor"]})
                machine, created = Machine.objects.update_or_create(
                    vendor=vendor, model_name=spec["model_name"],
                    defaults={"category": cat, "aliases": spec["aliases"],
                             "slug": spec["slug"], "is_supported": True})
                n_machines += 1 if created else 0

            for filename in spec["files"]:
                path = src / filename
                if not path.exists():
                    self.stderr.write(self.style.ERROR(f"Missing manual file: {path}"))
                    n_missing_files += 1
                    continue
                text = path.read_text(encoding="utf-8")
                sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if dry:
                    self.stdout.write(f"    + {filename} ({len(text)} chars)")
                    continue
                if MachineDocument.objects.filter(machine=machine, sha256=sha).exists():
                    n_skipped_docs += 1
                    continue
                MachineDocument.objects.create(
                    machine=machine, lang="sv", kind="manual",
                    parsed_text=text, token_estimate=max(len(text) // 4, 0), sha256=sha)
                n_docs += 1

        if dry:
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Loaded: {n_machines} new machine(s), {n_docs} new document(s), "
                f"{n_skipped_docs} document(s) unchanged (skipped)."))
