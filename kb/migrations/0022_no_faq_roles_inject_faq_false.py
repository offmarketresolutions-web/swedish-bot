"""Make the inject_faq flag tell the truth for the four roles that never get FAQ.

Spec §10 and §11 both require FAQ injection to stay disabled for the safety classifier
and the session summarizer. The BEHAVIOUR has always been correct, but not for the
reason the dashboard implies: chat/context.py's injection gate reads
`prompts.config_for("specialist")` — hard-coded to the specialist role — so the flag on
any other role's row is never consulted at all.

That left AgentPrompt.inject_faq sitting at its True default for router, summarizer,
safety and qa, and the owner's dashboard showing the exact opposite of what the spec
requires. A config surface that lies is a future bug: the first time someone wires that
gate to the calling role (the obvious "fix"), four roles start injecting FAQ silently.

seed_kb is deliberately no-clobber (get_or_create), so changing the seed default only
helps a fresh install — every existing install keeps True. `seed_kb --force` would
converge it but also overwrites owner-edited prompt bodies, which is the version-drift
bug that no-clobber exists to prevent. Hence a data migration: it touches one boolean
on four rows and nothing else.
"""
from django.db import migrations

NO_FAQ_ROLES = ["router", "summarizer", "safety", "qa"]


def disable(apps, schema_editor):
    apps.get_model("kb", "AgentPrompt").objects.filter(
        role__in=NO_FAQ_ROLES).update(inject_faq=False)


def restore(apps, schema_editor):
    # Reverse to the old field default so the migration is honestly reversible. This
    # does not re-enable any injection — nothing reads these rows' flag.
    apps.get_model("kb", "AgentPrompt").objects.filter(
        role__in=NO_FAQ_ROLES).update(inject_faq=True)


class Migration(migrations.Migration):

    dependencies = [("kb", "0021_machinedocument_alarm_codes_and_more")]

    operations = [migrations.RunPython(disable, restore)]
