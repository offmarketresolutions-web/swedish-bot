"""Dump the editable agent config (prompts, guardrails, chips, flow, routing rules)
to a single JSON document on stdout, so it can be moved between environments
(prod VPS <-> local dev) without a DB dump/restore.

    python manage.py export_agent_config > export.json

On the VPS:
    docker compose -f docker-compose.prod.yaml exec web \
        python manage.py export_agent_config > export.json
"""
import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from kb import models as m

SCHEMA_VERSION = 1


def _prompt_row(p: m.AgentPrompt) -> dict:
    return {
        "role": p.role,
        "body": p.body,
        "language_directive": p.language_directive,
        "model_id": p.model_id,
        "temperature": p.temperature,
        "thinking_enabled": p.thinking_enabled,
        "thinking_budget": p.thinking_budget,
        "max_output_tokens": p.max_output_tokens,
        "inject_faq": p.inject_faq,
        "faq_categories": sorted(p.faq_categories.values_list("slug", flat=True)),
        "prompt_version": p.prompt_version,
        "is_active": p.is_active,
    }


def _guardrail_row(g: m.AgentGuardrail) -> dict:
    return {
        "role": g.role,
        "rule": g.rule,
        "is_active": g.is_active,
        "order": g.order,
    }


def _chip_row(c: m.QuickReplyChip) -> dict:
    return {
        "intake_step": c.intake_step,
        "category": c.category.slug if c.category_id else None,
        "value": c.value,
        "order": c.order,
        "is_active": c.is_active,
        "texts": {t.lang: t.label for t in c.texts.all()},
    }


def _flow_row(f: m.FlowConfig) -> dict:
    return {"id": f.pk, "graph": f.graph}


def _routing_rule_row(r: m.RoutingRule) -> dict:
    return {
        "name": r.name,
        "match_category": r.match_category.slug if r.match_category_id else None,
        "match_problem_category": (
            f"{r.match_problem_category.category.slug}/{r.match_problem_category.slug}"
            if r.match_problem_category_id else None
        ),
        "match_severity": r.match_severity,
        "match_keyword": r.match_keyword,
        "action": r.action,
        "priority": r.priority,
        "is_active": r.is_active,
    }


class Command(BaseCommand):
    help = "Export AgentPrompt/AgentGuardrail/QuickReplyChip/FlowConfig/RoutingRule to JSON (stdout)."

    def handle(self, *args, **opts):
        payload = {
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "agent_prompts": [_prompt_row(p) for p in m.AgentPrompt.objects.order_by("role")],
            "agent_guardrails": [_guardrail_row(g) for g in m.AgentGuardrail.objects.order_by("role", "order")],
            "quick_reply_chips": [
                _chip_row(c) for c in
                m.QuickReplyChip.objects.select_related("category").prefetch_related("texts")
                .order_by("intake_step", "order")
            ],
            "flow_configs": [_flow_row(f) for f in m.FlowConfig.objects.order_by("pk")],
            "routing_rules": [
                _routing_rule_row(r) for r in
                m.RoutingRule.objects.select_related("match_category", "match_problem_category__category")
                .order_by("-priority", "id")
            ],
        }
        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
