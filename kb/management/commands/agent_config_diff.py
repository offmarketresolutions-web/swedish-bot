"""Show which AgentPrompt/QuickReplyChip rows in the DB have drifted from the
repo's seed_kb.py code defaults — i.e. what an owner has edited in the dashboard.

Read-only, changes nothing. Run this before a deploy/redeploy to confirm nothing
will be lost, and after `seed_kb` to sanity-check first-boot state.

    python manage.py agent_config_diff
"""
from django.core.management.base import BaseCommand

from core.constants import MODELS
from kb import models as m
from kb.seed_prompts import LANGUAGE_DIRECTIVE, all_prompts

PROMPT_DEFAULT_FIELDS = ["body", "language_directive", "model_id"]


class Command(BaseCommand):
    help = "Read-only: list AgentPrompt/QuickReplyChip rows that differ from seed_kb.py defaults."

    def handle(self, *args, **opts):
        edited = []

        for role, (body, model_role) in all_prompts().items():
            defaults = {"body": body, "language_directive": LANGUAGE_DIRECTIVE,
                        "model_id": MODELS[model_role]}
            try:
                obj = m.AgentPrompt.objects.get(role=role)
            except m.AgentPrompt.DoesNotExist:
                edited.append(f"AgentPrompt[{role}]: missing from DB (seed_kb has not run)")
                continue
            diffs = [f for f in PROMPT_DEFAULT_FIELDS if getattr(obj, f) != defaults[f]]
            if diffs:
                edited.append(f"AgentPrompt[{role}]: owner-edited field(s) {diffs}")

        db_roles = set(m.AgentPrompt.objects.values_list("role", flat=True))
        seed_roles = set(all_prompts().keys())
        for extra in sorted(db_roles - seed_roles):
            edited.append(f"AgentPrompt[{extra}]: exists in DB but not in seed_kb.py (custom role)")

        if not edited:
            self.stdout.write(self.style.SUCCESS(
                "No drift — DB AgentPrompt rows match seed_kb.py code defaults."))
            return

        self.stdout.write(self.style.WARNING(
            f"{len(edited)} row(s) differ from repo defaults (owner edits — a deploy "
            f"will NOT touch these, since seed_kb no longer overwrites existing rows):"))
        for line in edited:
            self.stdout.write(f"  - {line}")
