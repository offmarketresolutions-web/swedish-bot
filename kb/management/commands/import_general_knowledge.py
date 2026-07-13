"""Import the general-knowledge FAQ package (V2 plan §D2 / Sprint S1) into the
approval-gated corpus: faq_type=site rows become kb.SiteFAQ, faq_type=category
rows become kb.FAQEntry (+ FAQEntryText[lang=sv]). ALL imported rows land
is_approved=False — the package README states every technical answer is a
conversation-derived draft requiring Nordland VVS review before production; the
retrieval-approval filter (kb/semantic.py, chat/context.py) already excludes
unapproved rows, so this import is safe to run against a live DB.

Idempotent by faq_id (FAQEntry.source_id / SiteFAQ.slug=slugify(faq_id)): a
second run updates content but never resets an already-approved row back to
unapproved (Django 5's update_or_create create_defaults= only applies on the
INITIAL create).

    python manage.py import_general_knowledge <path.zip|path.json> [--dry-run]
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

# zip category_slug -> our seeded Category tree slug (V2 plan §D2 SLUG_MAP).
# "heat_pump" is the identity case (the zip's generic heat-pump entries attach
# directly to the parent category, no subtype leaf). radiators/floor_heating
# are NOT in the seeded tree — created as heat_pump leaves on first encounter
# (flagged deviation from the owner's category_slug naming, see plan D2).
CATEGORY_SLUG_MAP = {
    "heat_pump": "heat_pump",
    "heat_pump_liquid_water": "water_to_water",
    "heat_pump_air_water": "air_to_water",
    "heat_pump_air_air": "air_to_air",
    "heat_pump_exhaust_air": "exhaust_air",
    "water_pump_well": "water_pump_well",
    "water_filtration": "water_filtration",
    "radiators": "radiators",
    "floor_heating": "floor_heating",
}

# How to create each target Category if a fresh deploy hasn't seeded it yet
# (name, parent_slug|None, group). Covers every value CATEGORY_SLUG_MAP can
# produce, so the importer never crashes on a missing category — it creates
# the leaf under the right parent and logs it (plan requirement).
CATEGORY_SPECS = {
    "heat_pump": ("Heat pump", None, "heat"),
    "water_to_water": ("Water-to-water", "heat_pump", "heat"),
    "air_to_water": ("Air-to-water", "heat_pump", "heat"),
    "air_to_air": ("Air-to-air", "heat_pump", "air"),
    "exhaust_air": ("Exhaust air", "heat_pump", "heat"),
    "water_pump_well": ("Water pump & well", None, "water"),
    "water_filtration": ("Water filtration", None, "water"),
    "radiators": ("Radiators", "heat_pump", "heat"),
    "floor_heating": ("Floor heating", "heat_pump", "heat"),
}

# zip subtype vocab -> our vocab. Unlisted values (air_to_water, air_to_air,
# exhaust_air, submersible_pump, jet_pump, pressure_system, well) pass through
# verbatim. "all" is handled separately (-> empty list = applies to everything).
SUBTYPE_MAP = {
    "liquid_to_water": "water_to_water",
}


def normalize_subtypes(subtypes: list[str]) -> list[str]:
    """zip applicable_subtypes -> our vocab. ["all"] (or empty) -> [] (no
    restriction). Pure function so it's unit-testable without a DB."""
    if not subtypes or "all" in subtypes:
        return []
    return [SUBTYPE_MAP.get(s, s) for s in subtypes]


def _load_entries(path: Path) -> list[dict]:
    """Read the package JSON, whether given as a bare .json file or the
    distributed .zip (finds the first *.json member). utf-8 explicit (Swedish
    chars)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            json_names = [n for n in zf.namelist() if n.lower().endswith(".json")]
            if not json_names:
                raise CommandError(f"No .json member found in {path}")
            raw = zf.read(json_names[0]).decode("utf-8")
    else:
        raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise CommandError("Package JSON has no top-level 'entries' list.")
    return entries


class Command(BaseCommand):
    help = "Import the general-knowledge FAQ package (zip or json) — lands unapproved."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Path to the .zip package or a bare .json file.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from kb.models import Category, FAQEntry, FAQEntryText, SiteFAQ

        path = Path(opts["source"])
        if not path.exists():
            raise CommandError(f"Not found: {path}")
        entries = _load_entries(path)

        dry = opts["dry_run"]
        cat_cache: dict[str, Category] = {}

        def resolve_category(our_slug: str) -> Category | None:
            if our_slug in cat_cache:
                return cat_cache[our_slug]
            cat = Category.objects.filter(slug=our_slug).first()
            if cat is None:
                spec = CATEGORY_SPECS.get(our_slug)
                if spec is None:
                    return None
                name, parent_slug, group = spec
                parent = resolve_category(parent_slug) if parent_slug else None
                if dry:
                    self.stdout.write(f"  [would create category] {our_slug} (parent={parent_slug})")
                else:
                    cat, created = Category.objects.get_or_create(
                        slug=our_slug, defaults={"name": name, "parent": parent, "group": group})
                    if created:
                        self.stdout.write(self.style.WARNING(
                            f"Created missing Category leaf: {our_slug} (parent={parent_slug or '-'})"))
            cat_cache[our_slug] = cat
            return cat

        n_site_created = n_site_updated = 0
        n_faq_created = n_faq_updated = 0
        n_skipped = 0
        created_leaves: list[str] = []

        for entry in entries:
            faq_id = (entry.get("faq_id") or "").strip()
            if not faq_id:
                n_skipped += 1
                continue
            faq_type = entry.get("faq_type")

            if faq_type == "site":
                slug = slugify(faq_id)
                fields = {
                    "topic": (entry.get("subcategory_slug") or "")[:64],
                    "question": (entry.get("question_sv") or "")[:300],
                    "answer": entry.get("answer_sv") or "",
                    "lang": "sv",
                    "is_active": True,
                }
                if dry:
                    self.stdout.write(f"[site] {faq_id} -> SiteFAQ(slug={slug})")
                    continue
                obj, created = SiteFAQ.objects.update_or_create(
                    slug=slug, defaults=fields, create_defaults={**fields, "is_approved": False})
                n_site_created += created
                n_site_updated += not created

            elif faq_type == "category":
                our_slug = CATEGORY_SLUG_MAP.get(entry.get("category_slug"))
                if our_slug is None:
                    self.stderr.write(self.style.ERROR(
                        f"Unknown category_slug {entry.get('category_slug')!r} on {faq_id} — skipped."))
                    n_skipped += 1
                    continue
                if our_slug not in cat_cache and not Category.objects.filter(slug=our_slug).exists() \
                        and our_slug in CATEGORY_SPECS:
                    created_leaves.append(our_slug)
                category = resolve_category(our_slug)
                if category is None:
                    self.stderr.write(self.style.ERROR(f"No category for {faq_id} ({our_slug}) — skipped."))
                    n_skipped += 1
                    continue

                subtypes = normalize_subtypes(entry.get("applicable_subtypes") or [])
                shared = {
                    "source_type": (entry.get("source_type") or "")[:64],
                    "applicable_subtypes": subtypes,
                    "onset_type": (entry.get("onset_type") or "")[:12],
                    "safe_customer_checks": entry.get("safe_customer_checks") or "",
                    "service_trigger": entry.get("service_trigger") or "",
                    "keywords": entry.get("keywords") or [],
                }
                if dry:
                    self.stdout.write(f"[category] {faq_id} -> FAQEntry(category={our_slug})")
                    continue
                obj, created = FAQEntry.objects.update_or_create(
                    source_id=faq_id,
                    defaults={"category": category, **shared},
                    create_defaults={"category": category, "key": slugify(faq_id)[:64] or faq_id.lower(),
                                     "is_approved": False, **shared},
                )
                n_faq_created += created
                n_faq_updated += not created
                if not dry:
                    FAQEntryText.objects.update_or_create(
                        faq=obj, lang="sv",
                        defaults={"question": entry.get("question_sv") or "",
                                 "answer": entry.get("answer_sv") or ""})
            else:
                self.stderr.write(self.style.ERROR(f"Unknown faq_type {faq_type!r} on {faq_id} — skipped."))
                n_skipped += 1

        if dry:
            self.stdout.write(self.style.SUCCESS(f"Dry run: {len(entries)} entries parsed."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"FAQEntry: {n_faq_created} created, {n_faq_updated} updated. "
            f"SiteFAQ: {n_site_created} created, {n_site_updated} updated. "
            f"{n_skipped} skipped."
            + (f" New category leaves: {', '.join(sorted(set(created_leaves)))}." if created_leaves else "")))
