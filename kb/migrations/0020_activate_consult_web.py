"""Flip the consult_web Tool row live now that chat.consult.consult_web exists
(0019 seeded it is_active=False as a placeholder)."""
from django.db import migrations


def activate(apps, schema_editor):
    apps.get_model("kb", "Tool").objects.filter(slug="consult_web").update(is_active=True)


def deactivate(apps, schema_editor):
    apps.get_model("kb", "Tool").objects.filter(slug="consult_web").update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("kb", "0019_vendor_official_domains_seed_consult_web")]
    operations = [migrations.RunPython(activate, deactivate)]
