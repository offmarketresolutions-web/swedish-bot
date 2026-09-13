"""Render agent prompts + resolve the model id from the DB (plan §7).

model_id lives on AgentPrompt (single source of truth) — code never hardcodes
which model an agent uses; editing the row in admin changes it with no redeploy.
"""
from __future__ import annotations

from core.agent_registry import ROLE_INFO
from core.constants import MODELS
from kb.models import AgentPrompt
from kb.seed_prompts import GAS_EXCEPTION, GAS_EXCEPTION_CLASSIFIER

# Safety backstop: if the AgentPrompt row for a role is missing or was deactivated
# (both admin-reachable states), `render()` must never hand the model a blank/near-
# blank system instruction -- that means an LLM call with no persona and no rules.
# This is deliberately generic and conservative (no domain claims, no promises),
# used only until the owner restores/creates a real row.
_FALLBACK_BODY = (
    "You are Nordland VVS's customer service assistant, currently running with no "
    "configured agent prompt for this role. Do NOT diagnose, troubleshoot, or give "
    "technical/safety advice. Do NOT invent facts. Briefly apologise, say a human "
    "technician needs to help with this, and ask the customer to leave contact "
    "details so staff can follow up."
)

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


# Derived from core.agent_registry (single source of truth for which roles are
# "general" specialists) rather than duplicated here, so a registry change can't
# silently drop a role from the contract addenda below (tests/test_agent_registry.py
# and test_prompt_contract.py both pin the derived tuples).
_GENERAL_ROLES = tuple(r for r, info in ROLE_INFO.items() if info.layer == "general")
_SPECIALIST_ROLES = ("specialist",) + _GENERAL_ROLES

# Code-owned OUTPUT CONTRACT keys, appended ONLY when the DB body doesn't already
# declare them. seed_kb is deliberately no-clobber for AgentPrompt.body (an owner's
# dashboard edit must survive a redeploy), which means a deploy never updates an
# edited prompt — so a feature whose contract key was added in code would read
# `data.get(key)` forever against an older body that never emits it, and fail
# silently. Keeping the contract in code guarantees agent output and backend stay
# aligned no matter how the prompt was edited. Idempotent: a freshly seeded body
# already contains the key, so nothing is appended and the text is never duplicated.
_CONTRACT_ADDENDA: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("no_action_needed", _SPECIALIST_ROLES,
     'Also include "no_action_needed": true/false in your JSON. Set it true when the '
     'correct answer is that the situation is normal and no action or visit is needed '
     '(a documented reassurance) — that is a valid decision="solve" provided it meets '
     "the same in-docs and confidence bar. Never set it true for anything you were "
     "unsure about or that involves a safety-scope task."),
    # Spec §7: the always/gradual-vs-sudden distinction is what decides between offering a
    # documented customer setting and offering service (§8). Across 100 live conversations
    # onset went uncaptured in 67 — nothing ever ASKS for it, it is only extracted when a
    # customer volunteers it — so the specialist could not apply the rule and escalated by
    # default. Keyed on "onset": a freshly seeded body that already handles it is untouched.
    ("onset is unknown", _SPECIALIST_ROLES,
     'When the customer reports a COMFORT or PERFORMANCE problem (too cold, too warm, less '
     'hot water, weaker heating/cooling, poorer output) and you do not yet know the onset, '
     'ask ONE short question before giving a verdict: has it always been like this or come '
     'on gradually, or did it change suddenly after working normally? Report it as '
     '"onset": "always" | "gradual" | "sudden". Always/gradual means a documented normal '
     'user setting may be appropriate (explain what it affects, note the original value, '
     'one small change at a time). Sudden means do NOT simply raise the curve or the '
     'hot-water setting — check alarms, operating mode, schedules, holiday mode, power '
     'interruption, pressure, circulation or backup heat first, and offer Nordland VVS '
     'service when no user-setting change explains it.'),
    ("consult_web", _GENERAL_ROLES,
     'You may also include "consult_web": {{"question": "<one specific question>"}} '
     "(or null) to consult OFFICIAL manufacturer sources for identification, "
     "specifications or normal customer controls. Never base a repair or service "
     "procedure on a web source, and information from the web NEVER sets in_docs=true."),
)


def contract_addendum(role: str, body: str) -> str:
    """The code-owned contract lines this role needs that `body` doesn't already declare."""
    missing = [text for key, roles, text in _CONTRACT_ADDENDA
               if role in roles and key not in (body or "")]
    if not missing:
        return ""
    return ("\n\nOUTPUT CONTRACT (required by the backend):\n"
            + "\n".join(f"- {m}" for m in missing))


# Gas-safety exception (run100 S009 regression), same code-owned-addendum shape as
# _CONTRACT_ADDENDA above: seed_kb is no-clobber, so a prod prompt edited (or seeded)
# before this rule existed would otherwise never receive it. Keyed on the literal
# absence of "ignite" -- every fresh seed_prompts.py body already contains that word
# (via GAS_EXCEPTION / GAS_EXCEPTION_CLASSIFIER), so a freshly seeded body never
# triggers this and the text is never duplicated.
_GAS_EXCEPTION_ROLES = ("intake", "specialist", "intelligent_intake", "intelligent_specialist",
                        "heat_pump_specialist", "water_pump_specialist",
                        "water_filtration_specialist")


def safety_addendum(role: str, body: str) -> str:
    """The code-owned gas-safety exception this role needs when `body` doesn't already
    carry it (checked via the literal substring "ignite")."""
    if "ignite" in (body or ""):
        return ""
    if role in _GAS_EXCEPTION_ROLES:
        text = GAS_EXCEPTION
    elif role == "safety":
        text = GAS_EXCEPTION_CLASSIFIER
    else:
        return ""
    return "\n\nSAFETY (required by the backend):\n" + text


def render(role: str, *, locale: str = "en", **vars) -> str:
    """Return the full system instruction for an agent: body + language directive,
    with {placeholders} filled, then any staff-set guardrails. Missing placeholders are
    left blank, never crash."""
    agent = get_agent(role)
    body = (agent.body if agent else "") or _FALLBACK_BODY
    directive = agent.language_directive if agent else ""
    template = (body + contract_addendum(role, body) + safety_addendum(role, body)
                + (directive or ""))
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
