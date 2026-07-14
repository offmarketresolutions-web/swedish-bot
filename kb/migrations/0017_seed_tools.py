"""Seed the tool registry (V2 S9) with today's real agent capabilities."""
from django.db import migrations

TOOLS = [
    dict(slug="identify_machine", name="Identify machine", kind="internal",
         handler_ref="kb.identification",
         description="Trigram + embedding match of vendor/model from free text or a nameplate photo."),
    dict(slug="suggest_models", name="Suggest models", kind="internal",
         handler_ref="kb.identification",
         description="Offer the closest candidate machines when identification is ambiguous."),
    dict(slug="check_service_area", name="Check service area", kind="internal",
         handler_ref="crm.geo",
         description="Postcode/polygon lookup for whether we service the customer's address."),
    dict(slug="form_chip", name="Form / handoff chip", kind="internal",
         handler_ref="crm.form_buttons",
         description="Render a quick-reply chip that hands the customer to a booking/quote form."),
    dict(slug="request_photo", name="Request photo", kind="internal",
         handler_ref="chat.vision",
         description="Ask the customer for a photo (e.g. nameplate) via the chat vision flow."),
    dict(slug="consult_brand", name="Consult brand notes", kind="internal",
         handler_ref="chat.consult.consult_brand", is_active=False,
         description="Brand-notes digest on demand (not yet built — placeholder for the "
                     "conversation-core agent)."),
]


def seed(apps, schema_editor):
    Tool = apps.get_model("kb", "Tool")
    for t in TOOLS:
        t = dict(t)
        t.setdefault("is_active", True)
        Tool.objects.get_or_create(slug=t.pop("slug"), defaults=t)


def unseed(apps, schema_editor):
    Tool = apps.get_model("kb", "Tool")
    Tool.objects.filter(slug__in=[t["slug"] for t in TOOLS]).delete()


class Migration(migrations.Migration):
    dependencies = [("kb", "0016_tool_agentprompt_common_issues_agentprompt_tools")]
    operations = [migrations.RunPython(seed, unseed)]
