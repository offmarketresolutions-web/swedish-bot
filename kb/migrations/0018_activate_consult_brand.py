"""Flip the consult_brand Tool row live now that chat.consult.consult_brand exists
(0017 seeded it is_active=False as a placeholder)."""
from django.db import migrations


def activate(apps, schema_editor):
    Tool = apps.get_model("kb", "Tool")
    Tool.objects.filter(slug="consult_brand").update(is_active=True)


def deactivate(apps, schema_editor):
    Tool = apps.get_model("kb", "Tool")
    Tool.objects.filter(slug="consult_brand").update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("kb", "0017_seed_tools")]
    operations = [migrations.RunPython(activate, deactivate)]
