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
    cfg = {"model": model_for(role), "temperature": 0.4, "thinking_budget": 0, "max_output_tokens": None}
    if agent:
        if agent.temperature is not None:
            cfg["temperature"] = agent.temperature
        if agent.thinking_enabled and agent.thinking_budget:
            cfg["thinking_budget"] = agent.thinking_budget
        if agent.max_output_tokens:
            cfg["max_output_tokens"] = agent.max_output_tokens
    return cfg


def render(role: str, *, locale: str = "en", **vars) -> str:
    """Return the full system instruction for an agent: body + language directive,
    with {placeholders} filled. Missing placeholders are left blank, never crash."""
    agent = get_agent(role)
    body = agent.body if agent else ""
    directive = agent.language_directive if agent else ""
    template = body + (directive or "")
    safe = _SafeDict(locale=locale, **{k: ("" if v is None else v) for k, v in vars.items()})
    try:
        return template.format_map(safe)
    except (KeyError, IndexError, ValueError):
        return template  # never let prompt templating crash a turn


class _SafeDict(dict):
    def __missing__(self, key):
        return ""
