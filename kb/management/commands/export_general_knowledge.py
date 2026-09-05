"""Dump the general-knowledge corpus back into the exact JSON package shape that
`import_general_knowledge` reads, so it can be re-created on another install.

The distributed .zip is not in the repo — before this command the only copy of the
102-row corpus was a single dev Postgres volume, which is why a fresh production
deploy came up with 1 FAQEntry instead of 93.

    python manage.py export_general_knowledge out.json

Exports only what the package created: FAQEntry rows carrying a source_id, and
SiteFAQ rows with no source_url (the scraped nordlandvvs.se FAQ has one and is
seeded by its own command). Approval flags are deliberately NOT exported — the
importer lands every row unapproved and approval is the owner's editorial act on
the target install.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from .import_general_knowledge import CATEGORY_SLUG_MAP

# our seeded Category slug -> the package's category_slug. Inverting the import
# map keeps the two commands from drifting apart: a new category added there is
# automatically exportable here (and a value collision fails loudly at import).
OUR_TO_PACKAGE_SLUG = {v: k for k, v in CATEGORY_SLUG_MAP.items()}
assert len(OUR_TO_PACKAGE_SLUG) == len(CATEGORY_SLUG_MAP), "CATEGORY_SLUG_MAP values are not unique"


def build_package() -> dict:
    from kb.models import FAQEntry, SiteFAQ

    entries: list[dict] = []
    skipped: list[str] = []

    faqs = (FAQEntry.objects.exclude(source_id="")
            .select_related("category").prefetch_related("texts").order_by("source_id"))
    for faq in faqs:
        package_slug = OUR_TO_PACKAGE_SLUG.get(faq.category.slug)
        if package_slug is None:
            skipped.append(f"{faq.source_id} (category {faq.category.slug} has no package slug)")
            continue
        sv = next((t for t in faq.texts.all() if t.lang == "sv"), None)
        entries.append({
            "faq_id": faq.source_id,
            "faq_type": "category",
            "category_slug": package_slug,
            "applicable_subtypes": faq.applicable_subtypes or [],
            "onset_type": faq.onset_type,
            "source_type": faq.source_type,
            "safe_customer_checks": faq.safe_customer_checks,
            "service_trigger": faq.service_trigger,
            "keywords": faq.keywords or [],
            "question_sv": sv.question if sv else "",
            "answer_sv": sv.answer if sv else "",
        })

    for site in SiteFAQ.objects.filter(source_url="").order_by("slug"):
        entries.append({
            "faq_id": site.slug,
            "faq_type": "site",
            "subcategory_slug": site.topic,
            "question_sv": site.question,
            "answer_sv": site.answer,
        })

    return {"entries": entries, "_skipped": skipped}


class Command(BaseCommand):
    help = "Export the general-knowledge corpus as an import_general_knowledge JSON package."

    def add_arguments(self, parser):
        parser.add_argument("dest", help="Path to write the .json package to.")

    def handle(self, *args, **opts):
        package = build_package()
        skipped = package.pop("_skipped")
        entries = package["entries"]
        if not entries:
            raise CommandError("Nothing to export — no FAQEntry with a source_id and no package SiteFAQ.")
        Path(opts["dest"]).write_text(
            json.dumps(package, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        n_cat = sum(e["faq_type"] == "category" for e in entries)
        for line in skipped:
            self.stderr.write(self.style.ERROR(f"Skipped {line}"))
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {len(entries)} entries ({n_cat} category, {len(entries) - n_cat} site) "
            f"to {opts['dest']}." + (f" {len(skipped)} skipped." if skipped else "")))
