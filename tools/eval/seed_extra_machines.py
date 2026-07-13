"""One-off DB seeding for the eval harness: adds the 3 extra machines that the
test-plan scenario catalog references by name but are not in `seed_kb.py`'s
minimal catalog (IVT Geo 412C, IVT Vent 402, Bosch Greenline HE).

Mirrors `tests/test_scenarios/conftest.py::seeded` exactly (read-only reference,
not modified). Run AFTER `manage.py seed_kb` against the target DB:

    POSTGRES_DB=eval_nordland uv run python manage.py seed_kb
    POSTGRES_DB=eval_nordland uv run python tools/eval/seed_extra_machines.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from kb.models import Category, Machine, Vendor  # noqa: E402


def run():
    ivt = Vendor.objects.get(name="IVT")
    bosch = Vendor.objects.get(name="Bosch")
    water_to_water = Category.objects.get(slug="water_to_water")
    exhaust_air = Category.objects.get(slug="exhaust_air")

    _, c1 = Machine.objects.get_or_create(
        vendor=ivt, model_name="Geo 412C",
        defaults=dict(category=water_to_water, aliases=["geo412c", "geo 412c", "412c"],
                      slug="geo-412c", is_supported=True))
    _, c2 = Machine.objects.get_or_create(
        vendor=ivt, model_name="Vent 402",
        defaults=dict(category=exhaust_air, aliases=["vent402", "vent 402"],
                      slug="ivt-vent-402", is_supported=True))
    _, c3 = Machine.objects.get_or_create(
        vendor=bosch, model_name="Greenline HE",
        defaults=dict(category=water_to_water,
                      aliases=["greenline", "greenline he", "greenline hec-e"],
                      slug="greenline-he", is_supported=True))
    print(f"Extra machines: Geo 412C created={c1}, Vent 402 created={c2}, Greenline HE created={c3}")
    print(f"Total machines now: {Machine.objects.count()}")


if __name__ == "__main__":
    run()
