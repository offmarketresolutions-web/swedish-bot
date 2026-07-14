"""Seed the knowledge base with the category tree, starter vendors/machines,
controlled vocab, quick-reply chips, FAQ, and the default agent prompts.

Idempotent — safe to re-run. `python manage.py seed_kb`.
"""
from django.core.management.base import BaseCommand

from core.constants import MODELS
from kb import models as m
from kb.seed_prompts import LANGUAGE_DIRECTIVE, all_prompts

CATEGORIES = [
    ("Heat pump", "heat_pump", None, 0),
    ("Water-to-water", "water_to_water", "heat_pump", 0),
    ("Air-to-water", "air_to_water", "heat_pump", 1),
    ("Air-to-air", "air_to_air", "heat_pump", 2),
    ("Exhaust air", "exhaust_air", "heat_pump", 3),
    ("Water pump & well", "water_pump_well", None, 1),
    ("Water filtration", "water_filtration", None, 2),
]

VENDORS = ["IVT", "Bosch", "Grundfos", "Debe", "Scandia Pumps", "Aqua Expert", "Aqua Invent"]

MACHINES = [
    ("IVT", "exhaust_air", "IVT 490", ["ivt490", "490"]),
    ("IVT", "exhaust_air", "IVT 402", ["ivt402", "402"]),
    ("Bosch", "air_to_water", "Bosch Compress 7000i", ["compress 7000", "7000i"]),
    ("Grundfos", "water_pump_well", "Grundfos SQ", ["sq", "sqe"]),
    ("Debe", "water_pump_well", "Debe DPM", ["dpm"]),
]

PROBLEM_CATEGORIES = {
    "heat_pump": [("no_heat", "No heat"), ("error_code", "Error code on display"),
                  ("noise", "Strange noise"), ("leaking", "Leaking"), ("high_bills", "Higher bills")],
    "water_pump_well": [("no_water", "No water"), ("low_pressure", "Low pressure"),
                        ("runs_constantly", "Pump runs constantly"), ("wont_start", "Pump won't start")],
    "water_filtration": [("bad_taste", "Bad taste/smell"), ("discoloured", "Discoloured water"),
                         ("low_flow", "Low flow"), ("media_question", "Salt/media question")],
}

CHIPS = {
    "category": [("heat_pump", "Heat pump"), ("water_pump_well", "Water pump / well"),
                 ("water_filtration", "Water filtration"), ("unknown", "Not sure")],
    "brand": [(v, v) for v in VENDORS] + [("other", "Other / don't know")],
}

# Swedish chip labels (data-driven Swedish; plan §11). Brand names stay verbatim.
SV_LABELS = {
    "heat_pump": "Värmepump", "water_pump_well": "Vattenpump / brunn",
    "water_filtration": "Vattenfilter", "unknown": "Vet inte", "other": "Annat / vet inte",
    "no_heat": "Ingen värme", "error_code": "Felkod på displayen", "noise": "Konstigt ljud",
    "leaking": "Läcker", "high_bills": "Högre räkningar",
    "no_water": "Inget vatten", "low_pressure": "Lågt tryck",
    "runs_constantly": "Pumpen går konstant", "wont_start": "Pumpen startar inte",
    "bad_taste": "Dålig smak/lukt", "discoloured": "Missfärgat vatten",
    "low_flow": "Lågt flöde", "media_question": "Salt/media-fråga",
}


class Command(BaseCommand):
    help = ("Seed the knowledge base (idempotent). Prompts and chips are first-boot "
            "defaults only: an existing row is left untouched (owner edits in the "
            "dashboard survive re-seeds/redeploys). Pass --force to reset them back "
            "to the code defaults.")

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                             help="Overwrite existing AgentPrompt/QuickReplyChip rows "
                                  "with the code defaults (discards owner edits).")

    def handle(self, *args, **opts):
        force = opts["force"]
        cats = {}
        for name, slug, parent_slug, order in CATEGORIES:
            cats[slug], _ = m.Category.objects.update_or_create(
                slug=slug, defaults={"name": name, "order": order,
                                     "parent": cats.get(parent_slug)})
        vendors = {}
        for name in VENDORS:
            vendors[name], _ = m.Vendor.objects.update_or_create(
                slug=name.lower().replace(" ", "-"), defaults={"name": name})

        for vname, cat_slug, model_name, aliases in MACHINES:
            m.Machine.objects.update_or_create(
                vendor=vendors[vname], model_name=model_name,
                defaults={"category": cats[cat_slug], "aliases": aliases,
                          "slug": model_name.lower().replace(" ", "-"), "is_supported": True})

        for cat_slug, items in PROBLEM_CATEGORIES.items():
            for slug, label in items:
                m.ProblemCategory.objects.update_or_create(
                    category=cats[cat_slug], slug=slug, defaults={"label": label})

        def _chip(step, value, label, order, category=None):
            # get_or_create (not update_or_create): chips are first-boot defaults —
            # an owner may have re-ordered/relabeled one in the dashboard, and a
            # re-seed (e.g. on redeploy) must not silently discard that.
            if force:
                chip, _ = m.QuickReplyChip.objects.update_or_create(
                    intake_step=step, value=value, category=category, defaults={"order": order})
            else:
                chip, _ = m.QuickReplyChip.objects.get_or_create(
                    intake_step=step, value=value, category=category, defaults={"order": order})
            if force or not chip.texts.filter(lang="en").exists():
                m.QuickReplyChipText.objects.update_or_create(chip=chip, lang="en", defaults={"label": label})
            if value in SV_LABELS and (force or not chip.texts.filter(lang="sv").exists()):
                m.QuickReplyChipText.objects.update_or_create(
                    chip=chip, lang="sv", defaults={"label": SV_LABELS[value]})

        for step, items in CHIPS.items():
            for i, (value, label) in enumerate(items):
                _chip(step, value, label, i)
        for cat_slug, items in PROBLEM_CATEGORIES.items():
            for i, (value, label) in enumerate(items):
                _chip("problem", value, label, i, category=cats[cat_slug])

        faq, _ = m.FAQEntry.objects.update_or_create(
            category=cats["heat_pump"], key="alarm_first_steps", defaults={"order": 0})
        m.FAQEntryText.objects.update_or_create(
            faq=faq, lang="en",
            defaults={"question": "What should I do when my heat pump shows an alarm?",
                      "answer": "Note the exact alarm code on the display, then check the "
                                "extract-air filter is clean. Do not open any panels."})

        for role, (body, model_role) in all_prompts().items():
            # get_or_create (not update_or_create): AgentPrompt.body/model_id/etc are
            # owner-editable in the dashboard. Seeding must only create missing rows
            # on first boot, never overwrite a live-edited prompt on redeploy —
            # that was the version-drift bug. --force resets to code defaults.
            defaults = {"body": body, "language_directive": LANGUAGE_DIRECTIVE,
                        "model_id": MODELS[model_role], "is_active": True}
            if force:
                m.AgentPrompt.objects.update_or_create(role=role, defaults=defaults)
            else:
                m.AgentPrompt.objects.get_or_create(role=role, defaults=defaults)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {m.Category.objects.count()} categories, {m.Vendor.objects.count()} vendors, "
            f"{m.Machine.objects.count()} machines, {m.AgentPrompt.objects.count()} prompts, "
            f"{m.QuickReplyChip.objects.count()} chips."))
