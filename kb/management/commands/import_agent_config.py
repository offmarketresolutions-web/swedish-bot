"""Reconcile the local DB's agent config (prompts/guardrails/chips/flow/routing
rules) against a JSON export produced by `export_agent_config` — the mechanism for
moving prod's owner-edited config onto a dev box, or vice versa.

Matches rows by natural key (role for prompts/guardrails, intake_step+category+value
for chips, name for routing rules, pk for flow). Never deletes rows absent from the
file — a partial export can't destroy data.

    python manage.py import_agent_config export.json              # dry-run diff
    python manage.py import_agent_config export.json --prefer file  # apply file -> db
"""
import json

from django.core.management.base import BaseCommand, CommandError

from kb import models as m

PROMPT_FIELDS = [
    "body", "language_directive", "model_id", "temperature", "thinking_enabled",
    "thinking_budget", "max_output_tokens", "inject_faq", "prompt_version", "is_active",
]
GUARDRAIL_FIELDS = ["rule", "is_active", "order"]
CHIP_FIELDS = ["order", "is_active"]


class Command(BaseCommand):
    help = "Reconcile DB agent config against a JSON export (dry-run diff by default)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Path to a JSON file produced by export_agent_config.")
        parser.add_argument("--dry-run", action="store_true", default=True,
                             help="Print the diff only; do not write (default).")
        parser.add_argument("--prefer", choices=["db", "file"], default=None,
                             help="file: overwrite DB rows that differ from the file. "
                                  "db: no-op (DB already wins); reports diff only.")

    def handle(self, *args, **opts):
        path = opts["file"]
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            raise CommandError(f"No such file: {path}")
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON in {path}: {e}")

        apply_changes = opts["prefer"] == "file"
        diffs = []
        diffs += self._diff_prompts(data.get("agent_prompts", []), apply_changes)
        diffs += self._diff_guardrails(data.get("agent_guardrails", []), apply_changes)
        diffs += self._diff_chips(data.get("quick_reply_chips", []), apply_changes)
        diffs += self._diff_routing_rules(data.get("routing_rules", []), apply_changes)

        if not diffs:
            self.stdout.write(self.style.SUCCESS("No differences — DB already matches the file."))
            return

        self.stdout.write(f"{'Applied' if apply_changes else 'Would change'} "
                           f"{len(diffs)} row(s):")
        for d in diffs:
            self.stdout.write(f"  [{d['kind']}] {d['key']}")
            for field, (old, new) in d["fields"].items():
                self.stdout.write(f"      {field}: {old!r} -> {new!r}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "\nDry-run only — nothing written. Re-run with --prefer file to apply."))

    # -- prompts --------------------------------------------------------
    def _diff_prompts(self, rows, apply_changes):
        out = []
        for row in rows:
            try:
                obj = m.AgentPrompt.objects.get(role=row["role"])
            except m.AgentPrompt.DoesNotExist:
                if apply_changes:
                    obj = m.AgentPrompt(role=row["role"])
                    for f in PROMPT_FIELDS:
                        setattr(obj, f, row[f])
                    obj.save()
                    if row.get("faq_categories"):
                        obj.faq_categories.set(
                            m.Category.objects.filter(slug__in=row["faq_categories"]))
                out.append({"kind": "AgentPrompt", "key": row["role"],
                            "fields": {"<new row>": (None, "created")}})
                continue

            changed = {}
            for f in PROMPT_FIELDS:
                old = getattr(obj, f)
                new = row.get(f)
                if old != new:
                    changed[f] = (old, new)
                    if apply_changes:
                        setattr(obj, f, new)
            current_cats = sorted(obj.faq_categories.values_list("slug", flat=True))
            new_cats = sorted(row.get("faq_categories") or [])
            if current_cats != new_cats:
                changed["faq_categories"] = (current_cats, new_cats)
                if apply_changes:
                    obj.faq_categories.set(m.Category.objects.filter(slug__in=new_cats))
            if changed:
                if apply_changes:
                    obj.save()
                out.append({"kind": "AgentPrompt", "key": row["role"], "fields": changed})
        return out

    # -- guardrails -------------------------------------------------------
    def _diff_guardrails(self, rows, apply_changes):
        out = []
        for row in rows:
            obj, created = m.AgentGuardrail.objects.get_or_create(
                role=row["role"], rule=row["rule"],
                defaults={"is_active": row["is_active"], "order": row["order"]})
            if created:
                out.append({"kind": "AgentGuardrail", "key": f"{row['role']}:{row['rule'][:30]}",
                            "fields": {"<new row>": (None, "created")}})
                continue
            changed = {}
            for f in ["is_active", "order"]:
                old = getattr(obj, f)
                new = row.get(f)
                if old != new:
                    changed[f] = (old, new)
                    if apply_changes:
                        setattr(obj, f, new)
            if changed:
                if apply_changes:
                    obj.save()
                out.append({"kind": "AgentGuardrail", "key": f"{row['role']}:{row['rule'][:30]}",
                            "fields": changed})
        return out

    # -- quick reply chips ------------------------------------------------
    def _diff_chips(self, rows, apply_changes):
        out = []
        for row in rows:
            category = None
            if row.get("category"):
                category = m.Category.objects.filter(slug=row["category"]).first()
            try:
                obj = m.QuickReplyChip.objects.get(
                    intake_step=row["intake_step"], value=row["value"], category=category)
            except m.QuickReplyChip.DoesNotExist:
                if apply_changes:
                    obj = m.QuickReplyChip.objects.create(
                        intake_step=row["intake_step"], value=row["value"], category=category,
                        order=row["order"], is_active=row["is_active"])
                    for lang, label in (row.get("texts") or {}).items():
                        m.QuickReplyChipText.objects.update_or_create(
                            chip=obj, lang=lang, defaults={"label": label})
                key = f"{row['intake_step']}/{row.get('category')}/{row['value']}"
                out.append({"kind": "QuickReplyChip", "key": key,
                            "fields": {"<new row>": (None, "created")}})
                continue

            key = f"{row['intake_step']}/{row.get('category')}/{row['value']}"
            changed = {}
            for f in CHIP_FIELDS:
                old = getattr(obj, f)
                new = row.get(f)
                if old != new:
                    changed[f] = (old, new)
                    if apply_changes:
                        setattr(obj, f, new)
            current_texts = {t.lang: t.label for t in obj.texts.all()}
            new_texts = row.get("texts") or {}
            if current_texts != new_texts:
                changed["texts"] = (current_texts, new_texts)
                if apply_changes:
                    for lang, label in new_texts.items():
                        m.QuickReplyChipText.objects.update_or_create(
                            chip=obj, lang=lang, defaults={"label": label})
            if changed:
                if apply_changes:
                    obj.save()
                out.append({"kind": "QuickReplyChip", "key": key, "fields": changed})
        return out

    # -- routing rules ------------------------------------------------
    def _diff_routing_rules(self, rows, apply_changes):
        out = []
        for row in rows:
            match_category = (m.Category.objects.filter(slug=row["match_category"]).first()
                               if row.get("match_category") else None)
            match_problem_category = None
            if row.get("match_problem_category"):
                cat_slug, pc_slug = row["match_problem_category"].split("/", 1)
                match_problem_category = m.ProblemCategory.objects.filter(
                    category__slug=cat_slug, slug=pc_slug).first()

            try:
                obj = m.RoutingRule.objects.get(name=row["name"])
            except m.RoutingRule.DoesNotExist:
                if apply_changes:
                    m.RoutingRule.objects.create(
                        name=row["name"], match_category=match_category,
                        match_problem_category=match_problem_category,
                        match_severity=row["match_severity"], match_keyword=row["match_keyword"],
                        action=row["action"], priority=row["priority"], is_active=row["is_active"])
                out.append({"kind": "RoutingRule", "key": row["name"],
                            "fields": {"<new row>": (None, "created")}})
                continue

            changed = {}
            simple_fields = ["match_severity", "match_keyword", "action", "priority", "is_active"]
            for f in simple_fields:
                old = getattr(obj, f)
                new = row.get(f)
                if old != new:
                    changed[f] = (old, new)
                    if apply_changes:
                        setattr(obj, f, new)
            if obj.match_category_id != (match_category.id if match_category else None):
                changed["match_category"] = (
                    obj.match_category.slug if obj.match_category_id else None,
                    row.get("match_category"))
                if apply_changes:
                    obj.match_category = match_category
            if obj.match_problem_category_id != (match_problem_category.id if match_problem_category else None):
                changed["match_problem_category"] = (
                    row.get("match_problem_category"), row.get("match_problem_category"))
                if apply_changes:
                    obj.match_problem_category = match_problem_category
            if changed:
                if apply_changes:
                    obj.save()
                out.append({"kind": "RoutingRule", "key": row["name"], "fields": changed})
        return out
