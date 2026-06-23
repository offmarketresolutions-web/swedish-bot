"""Seed safe, model-independent best-practice / FAQ guidance per category so the
specialist can resolve common low-complexity problems from the FAQ + best-practices
(not only the deep PDF). Idempotent: re-running updates bodies, never duplicates.

    python manage.py seed_guides
"""
from django.core.management.base import BaseCommand

from kb.models import Category, GenericGuide

# Applied to every heat-pump family (water_to_water, air_to_air, air_to_water, exhaust_air).
HEATPUMP_COMMON = [
    ("alarm_first_steps", "best_practice",
     "When the display shows an alarm or fault code: note the EXACT code, then check the "
     "user-serviceable filter is clean and any visible shut-off/isolation valve is open. A "
     "large share of alarms (low-flow, reduced heat) clear after cleaning the filter. Never "
     "open a sealed panel, touch wiring, or work on the sealed refrigerant circuit."),
    ("filter_maintenance", "best_practice",
     "Clean or replace the user-serviceable particle/air filter on the schedule in the manual "
     "(typically every 1-3 months). A clogged filter is the single most common cause of weak "
     "heat, low airflow and flow alarms, and cleaning it is a safe owner task."),
    ("no_heat_safe_checks", "guide",
     "Little or no heat: check the thermostat/setpoint is right, that the unit has power (look "
     "at the breaker — don't touch wiring), and that the filter is clean. If it still won't "
     "heat after those, it needs a Nordland technician."),
    ("annual_service", "faq",
     "We recommend an annual service of your heat pump — it keeps efficiency up, catches small "
     "issues early, and keeps the warranty valid."),
]

PER_CATEGORY = {
    "exhaust_air": [
        ("vent_filter_clean", "best_practice",
         "On a Vent exhaust-air unit, clean the particle filter about every two months — the "
         "display shows a 'clean filter' reminder. Switch the unit off, open the front cover, "
         "take out the filter, rinse or replace it, and refit. This is a safe owner task."),
    ],
    "water_pump_well": [
        ("low_pressure_checks", "guide",
         "Low or no water pressure: read the pressure gauge and confirm the main stop valve is "
         "open (look only). Do NOT adjust the pressure switch, the relief valve, or the pressure "
         "tank pre-charge — those are technician jobs on a pressurised system."),
    ],
    "water_filtration": [
        ("bad_taste_checks", "guide",
         "Bad taste or smell from filtered water: replace the filter cartridge on the manual's "
         "schedule and flush the system as the manual describes. If it persists after a fresh "
         "cartridge, book a technician or a water test."),
        ("cartridge_schedule", "faq",
         "Replace water-filter cartridges on the interval in your manual (commonly every "
         "6-12 months, sooner with heavy use or visibly dirty water)."),
    ],
}

HEATPUMP_FAMILIES = ["water_to_water", "air_to_air", "air_to_water", "exhaust_air", "heat_pump"]


class Command(BaseCommand):
    help = "Seed best-practice / FAQ GenericGuides per category (idempotent)."

    def handle(self, *args, **opts):
        n = 0
        plan = {}
        for slug in HEATPUMP_FAMILIES:
            plan.setdefault(slug, []).extend(HEATPUMP_COMMON)
        for slug, items in PER_CATEGORY.items():
            plan.setdefault(slug, []).extend(items)

        for slug, items in plan.items():
            cat = Category.objects.filter(slug=slug).first()
            if not cat:
                continue
            for key, kind, body in items:
                _, created = GenericGuide.objects.update_or_create(
                    category=cat, key=key, lang="en",
                    defaults={"kind": kind, "body": body})
                n += 1
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {n} guides across {GenericGuide.objects.values('category').distinct().count()} categories "
            f"({GenericGuide.objects.count()} total)."))
