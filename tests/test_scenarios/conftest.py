"""Fixtures for the mocked conversation scenario suite
(docs/plans/2026-07-12-test-plan-conversations.md). Local to this test dir per
the task boundary -- does not modify the root conftest.py or any production
seed data.

`seeded` runs the real `seed_kb` management command (IVT 490/402, Bosch
Compress 7000i, Grundfos SQ, Debe DPM) and then adds a few extra `Machine`
fixture rows for product lines the test plan's scenario catalog references by
name (IVT Geo 412C, IVT Vent 402, Bosch Greenline HE) that have raw manual
text at the repo root (`geo_troubleshooting.txt`, `vent_content.txt`,
`greenline_content.txt`) but are not yet loaded into `seed_kb.py`'s minimal
catalog (see docs/plans/2026-07-12-audit-current-state.md §7). This is
test-only fixture data -- it does not touch `kb/management/commands/seed_kb.py`.
"""
import pytest
from django.core.management import call_command


@pytest.fixture
def seeded():
    call_command("seed_kb")
    from kb.models import Category, Machine, Vendor

    ivt = Vendor.objects.get(name="IVT")
    bosch = Vendor.objects.get(name="Bosch")
    water_to_water = Category.objects.get(slug="water_to_water")
    exhaust_air = Category.objects.get(slug="exhaust_air")

    Machine.objects.get_or_create(
        vendor=ivt, model_name="Geo 412C",
        defaults=dict(category=water_to_water, aliases=["geo412c", "geo 412c", "412c"],
                      slug="geo-412c", is_supported=True))
    Machine.objects.get_or_create(
        vendor=ivt, model_name="Vent 402",
        defaults=dict(category=exhaust_air, aliases=["vent402", "vent 402"],
                      slug="ivt-vent-402", is_supported=True))
    Machine.objects.get_or_create(
        vendor=bosch, model_name="Greenline HE",
        defaults=dict(category=water_to_water,
                      aliases=["greenline", "greenline he", "greenline hec-e"],
                      slug="greenline-he", is_supported=True))
