"""Seed the non-catalog brand Vendors (plan S3 brand preservation).

Nordland services heat pumps of most brands — not just the 7 catalog brands. Seeding
these Vendor rows (is_active=True, NO machines) lets intake KEEP a stated brand verbatim
(NIBE / CTC / Thermia …) instead of squashing it to "other", and lets the general
specialist address the customer's unit by its real brand name. Idempotent.
"""
from django.db import migrations

BRAND_VENDORS = [
    "NIBE", "CTC", "Thermia", "Daikin", "Mitsubishi Electric", "Panasonic",
    "Toshiba", "Grundfos", "DAB", "Debe", "Callidus", "Aqua Expert",
]


def seed(apps, schema_editor):
    Vendor = apps.get_model("kb", "Vendor")
    for name in BRAND_VENDORS:
        slug = name.lower().replace(" ", "-")
        Vendor.objects.update_or_create(
            slug=slug, defaults={"name": name, "is_active": True})


def unseed(apps, schema_editor):
    # Non-destructive: only remove the rows that carry no machines (never touch catalog
    # vendors that gained machines meanwhile).
    Vendor = apps.get_model("kb", "Vendor")
    added = {n.lower().replace(" ", "-") for n in BRAND_VENDORS}
    Vendor.objects.filter(slug__in=added, machines__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("kb", "0011_faq_approval_metadata")]
    operations = [migrations.RunPython(seed, unseed)]
