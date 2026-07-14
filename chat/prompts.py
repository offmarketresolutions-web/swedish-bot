"""Render agent prompts + resolve the model id from the DB (plan §7).

model_id lives on AgentPrompt (single source of truth) — code never hardcodes
which model an agent uses; editing the row in admin changes it with no redeploy.
"""
from __future__ import annotations

from core.constants import MODELS
from kb.models import AgentPrompt

# Seed fallbacks if the DB row is missing (e.g. before seed_kb).
_FALLBACK_MODEL = {
    "intake": MODELS["flash_lite"], "router": MODELS["flash_lite"],
    "specialist": MODELS["flash"], "intelligent_intake": MODELS["flash"],
    "intelligent_specialist": MODELS["flash"],
    "heat_pump_specialist": MODELS["flash"], "water_pump_specialist": MODELS["flash"],
    "water_filtration_specialist": MODELS["flash"],
    "summarizer": MODELS["flash_lite"], "safety": MODELS["flash_lite"],
}


def get_agent(role: str) -> AgentPrompt | None:
    return AgentPrompt.objects.filter(role=role, is_active=True).first()


def model_for(role: str) -> str:
    agent = get_agent(role)
    return agent.model_id if agent and agent.model_id else _FALLBACK_MODEL.get(role, MODELS["flash"])


def config_for(role: str) -> dict:
    """Editable runtime config for an agent from the DB (V2 P-C): model, temperature,
    thinking budget, max output tokens. Null/0 fields fall back to code defaults."""
    agent = get_agent(role)
    cfg = {"model": model_for(role), "temperature": 0.4, "thinking_budget": 0,
           "max_output_tokens": None, "inject_faq": True, "faq_category_ids": []}
    if agent:
        if agent.temperature is not None:
            cfg["temperature"] = agent.temperature
        if agent.thinking_enabled and agent.thinking_budget:
            cfg["thinking_budget"] = agent.thinking_budget
        if agent.max_output_tokens:
            cfg["max_output_tokens"] = agent.max_output_tokens
        cfg["inject_faq"] = agent.inject_faq
        cfg["faq_category_ids"] = list(agent.faq_categories.values_list("id", flat=True))
    return cfg


def guardrails_block(role: str) -> str:
    """Staff-authored, ADD-ONLY guardrails for this agent (kb.AgentGuardrail), appended
    to the system instruction. Read fresh each turn so an edit is live immediately. The
    hard-coded code backstop (chat.guardrails) still runs regardless — this can only
    tighten behaviour, never weaken it."""
    from kb.models import AgentGuardrail
    rules = list(AgentGuardrail.objects.filter(role=role, is_active=True)
                 .values_list("rule", flat=True))
    if not rules:
        return ""
    lines = "\n".join(f"- {r.strip()}" for r in rules if r.strip())
    return ("\n\nADDITIONAL GUARDRAILS (set by Nordland staff — these ADD to and never "
            "weaken the rules above):\n" + lines)


def render(role: str, *, locale: str = "en", **vars) -> str:
    """Return the full system instruction for an agent: body + language directive,
    with {placeholders} filled, then any staff-set guardrails. Missing placeholders are
    left blank, never crash."""
    agent = get_agent(role)
    body = agent.body if agent else ""
    directive = agent.language_directive if agent else ""
    template = body + (directive or "")
    safe = _SafeDict(locale=locale, **{k: ("" if v is None else v) for k, v in vars.items()})
    try:
        out = template.format_map(safe)
    except (KeyError, IndexError, ValueError):
        out = template  # never let prompt templating crash a turn
    # Appended AFTER format_map so staff-entered braces can't break placeholder filling.
    return out + guardrails_block(role)


class _SafeDict(dict):
    def __missing__(self, key):
        return ""
