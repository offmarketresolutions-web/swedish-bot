"""Canonical agent-flow registry (single source of truth for the agents page).

The conversation flow is code (chat/orchestrator.py owns the FSM); this module
only describes it for staff-facing UI: which layer each AGENT_ROLE sits in, its
order left-to-right, and which knowledge-base family (dashboard/knowledge.py
FAMILIES) it draws from, if any.

Every value in core.enums.AGENT_ROLE_CHOICES must appear in exactly one layer
here — enforced by tests/test_agent_registry.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import AGENT_ROLE_CHOICES

_ROLE_LABELS = dict(AGENT_ROLE_CHOICES)


@dataclass(frozen=True)
class RoleInfo:
    role: str
    layer: str
    flow_position: str  # short badge, e.g. "1", "3", "3b"
    label_en: str
    label_sv: str
    blurb: str
    knowledge_family: str | None = None  # dashboard.knowledge.FAMILIES key, or None


@dataclass(frozen=True)
class Layer:
    key: str
    label_en: str
    label_sv: str
    roles: list[str] = field(default_factory=list)


# Ordered layers, left to right on the tab strip. A layer with 2+ roles renders
# as a hover/click dropdown; a layer with exactly 1 role renders as a plain tab.
LAYERS: list[Layer] = [
    Layer("intake", "Intake", "Intag", ["intake"]),
    Layer("routing", "Routing", "Routning", ["router"]),
    Layer("general", "General", "Allmänt", [
        "heat_pump_specialist", "water_pump_specialist", "water_filtration_specialist",
        "intelligent_specialist",
    ]),
    Layer("brand_specialist", "Brand specialist", "Märkesspecialist", ["specialist"]),
    Layer("fallback", "Fallback / unsupported", "Fallback / ej hanterad", [
        "intelligent_intake", "qa",
    ]),
    Layer("problem_resolution", "Problem resolution", "Ärendeavslut", ["summarizer"]),
    Layer("safety", "Safety", "Säkerhet", ["safety"]),
]

ROLE_INFO: dict[str, RoleInfo] = {
    "intake": RoleInfo(
        "intake", "intake", "1", "Intake agent", "Intagsagent",
        "Gathers the facts one at a time with quick-reply chips: equipment type, "
        "problem, brand/model (or a nameplate photo). Never diagnoses.",
    ),
    "router": RoleInfo(
        "router", "routing", "2", "Router agent", "Routningsagent",
        "Classifies the case and identifies the exact machine (trigram + embedding). "
        "Decides supported brand → Specialist, else → General or Intelligent intake.",
    ),
    "heat_pump_specialist": RoleInfo(
        "heat_pump_specialist", "general", "3-general", "Heat-pump general specialist",
        "Värmepump — allmän specialist",
        "Serviced category, no machine manual: safe general guidance for heat pumps.",
        knowledge_family="heat-pump",
    ),
    "water_pump_specialist": RoleInfo(
        "water_pump_specialist", "general", "3-general", "Water-pump / well general specialist",
        "Vattenpump/brunn — allmän specialist",
        "Serviced category, no machine manual: safe general guidance for water pumps and wells.",
        knowledge_family="water-pump-well",
    ),
    "water_filtration_specialist": RoleInfo(
        "water_filtration_specialist", "general", "3-general",
        "Water-filtration general specialist", "Vattenfiltrering — allmän specialist",
        "Serviced category, no machine manual: safe general guidance for water filtration.",
        knowledge_family="water-filtration",
    ),
    "intelligent_specialist": RoleInfo(
        "intelligent_specialist", "general", "3-general", "Intelligent specialist",
        "Intelligent specialist",
        "Serviced category with no manual and no dedicated general agent yet — spans "
        "multiple families, so no single knowledge corpus is wired here.",
    ),
    "specialist": RoleInfo(
        "specialist", "brand_specialist", "3", "Specialist agent", "Specialistagent",
        "Answers from the machine's full manual within a safe envelope. Solves only "
        "when confident + in-docs; otherwise escalates. Never instructs unsafe work.",
    ),
    "intelligent_intake": RoleInfo(
        "intelligent_intake", "fallback", "3b", "Intelligent intake specialist (unsupported)",
        "Intelligent intag (ej hanterad)",
        "Handles equipment we don't have manuals for: collects a qualified lead and "
        "escalates — no fabricated repair steps.",
    ),
    "qa": RoleInfo(
        "qa", "fallback", "v2", "QA / assessment agent (v2)", "QA/bedömningsagent (v2)",
        "Not yet wired into the live conversation flow (v2). Reserved role.",
    ),
    "summarizer": RoleInfo(
        "summarizer", "problem_resolution", "✎", "Session summarizer", "Sessionssammanfattare",
        "Writes the staff-facing AI summary of the conversation on close.",
    ),
    "safety": RoleInfo(
        "safety", "safety", "✓", "Safety classifier (guardrail backstop)",
        "Säkerhetsklassificerare (skyddsnät)",
        "Backstop that reviews specialist drafts and vetoes any unsafe instruction → "
        "forces escalation. The hard guardrail lives in code too.",
    ),
}


def ordered_roles() -> list[str]:
    """All roles, in flow order (layer order, then declaration order within layer)."""
    out: list[str] = []
    for layer in LAYERS:
        out.extend(layer.roles)
    return out


def layer_for_role(role: str) -> Layer | None:
    for layer in LAYERS:
        if role in layer.roles:
            return layer
    return None


def role_label(role: str) -> str:
    return _ROLE_LABELS.get(role, role)


def layers_ctx() -> list[dict]:
    """Template-friendly rendering of LAYERS: each layer's roles carry their
    display label alongside the raw role slug, so templates don't need a
    dict-lookup filter."""
    out = []
    for layer in LAYERS:
        roles = [{"role": r, "label": ROLE_INFO[r].label_en} for r in layer.roles]
        out.append({"key": layer.key, "label_en": layer.label_en, "label_sv": layer.label_sv,
                    "roles": roles})
    return out


# Sanity: every declared role must be a real AGENT_ROLE_CHOICES value.
assert set(ordered_roles()) <= set(_ROLE_LABELS), "agent_registry references an unknown role"
assert set(ROLE_INFO) == set(ordered_roles()), "ROLE_INFO / LAYERS mismatch"
