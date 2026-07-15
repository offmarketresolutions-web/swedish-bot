"""Backfill Customer profiles from existing conversation/case data (Customer File Hub).

Links older cases that captured contact facts in case_state to a Customer, keyed by
the peppered phone_hash. Uses the real crm.backfill.backfill_customers so the enrich
+ phone_hash logic stays in one place (acceptable for this one-off in a solo project).
Reverse is a no-op — we don't unlink customers.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    # Fresh DB (e.g. the test database): nothing to backfill — and calling the live-model
    # backfill here would crash, because later migrations (crm 0007+) add Session columns
    # that don't exist yet at this point in the graph. exists() selects no columns.
    Session = apps.get_model("crm", "Session")
    if not Session.objects.exists():
        return
    from crm.backfill import backfill_customers
    backfill_customers(
        session_model=Session,
        customer_model=apps.get_model("crm", "Customer"),
        enrich=False,
    )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0005_integrationsettings_customerfile_drive_url_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
