"""Assign each existing Category a top-level KB group (Heat / Air / Water).

Mapping reflects nordlandvvs.se: bergvärme/jordvärme (water_to_water), luft/vatten
(air_to_water) and frånluft (exhaust_air) are HEAT pumps; luft/luft (air_to_air) is
AIR; well pumps + filtration are WATER. Everything else stays 'other'."""
from django.db import migrations

GROUP_BY_SLUG = {
    "heat_pump": "heat",
    "water_to_water": "heat",
    "air_to_water": "heat",
    "exhaust_air": "heat",
    "air_to_air": "air",
    "water_pump_well": "water",
    "water_filtration": "water",
}


def set_groups(apps, schema_editor):
    Category = apps.get_model("kb", "Category")
    for cat in Category.objects.all():
        group = GROUP_BY_SLUG.get(cat.slug)
        if group and cat.group != group:
            cat.group = group
            cat.save(update_fields=["group"])


def noop(apps, schema_editor):
    # group is derivable from slug; reverse is intentionally a no-op (no data loss).
    pass


class Migration(migrations.Migration):
    dependencies = [("kb", "0006_sitefaq_category_group")]
    operations = [migrations.RunPython(set_groups, noop)]
