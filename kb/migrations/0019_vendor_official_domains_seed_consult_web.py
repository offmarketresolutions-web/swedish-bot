"""consult_web (official-manufacturer web research):
  - Vendor.official_domains — the per-brand allowlist the tool filters sources against.
  - Tool row for consult_web, seeded is_active=False (0020 flips it live), attached to
    the four general/no-manual specialist roles. Mirrors 0017/0018 for consult_brand.
"""
from django.db import migrations, models

TOOL = dict(
    slug="consult_web", name="Consult official web sources", kind="internal",
    handler_ref="chat.consult.consult_web", is_active=False,
    description="Grounded search of the brand's OFFICIAL manufacturer sites for "
                "identification/spec/control facts (never repair procedures).",
)

ROLES = ["intelligent_specialist", "heat_pump_specialist",
         "water_pump_specialist", "water_filtration_specialist"]

DOMAINS = {
    "nibe": ["nibe.eu", "nibe.se"],
    "ctc": ["ctc.se", "ctc-heating.com"],
    "thermia": ["thermia.com", "thermia.se"],
    "grundfos": ["grundfos.com", "product-selection.grundfos.com"],
    "callidus": ["callidus.se"],
}


def seed(apps, schema_editor):
    Tool = apps.get_model("kb", "Tool")
    AgentPrompt = apps.get_model("kb", "AgentPrompt")
    Vendor = apps.get_model("kb", "Vendor")
    t = dict(TOOL)
    tool, _ = Tool.objects.get_or_create(slug=t.pop("slug"), defaults=t)
    for role in ROLES:
        for agent in AgentPrompt.objects.filter(role=role):
            agent.tools.add(tool)
    for slug, domains in DOMAINS.items():
        v = Vendor.objects.filter(slug=slug).first()
        if v is not None and not v.official_domains:
            v.official_domains = domains
            v.save(update_fields=["official_domains"])


def unseed(apps, schema_editor):
    apps.get_model("kb", "Tool").objects.filter(slug="consult_web").delete()


class Migration(migrations.Migration):
    dependencies = [("kb", "0018_activate_consult_brand")]
    operations = [
        migrations.AddField(
            model_name="vendor",
            name="official_domains",
            field=models.JSONField(
                blank=True, default=list,
                help_text="Allowlist of official manufacturer hostnames (e.g. "
                          "['nibe.eu','nibe.se']). chat.consult.consult_web will only "
                          "digest web sources from these domains; empty means no web "
                          "research for this brand."),
        ),
        migrations.RunPython(seed, unseed),
    ]
