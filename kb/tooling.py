"""Read-side helper for the tool registry (V2 S9).

kb.models.Tool + AgentPrompt.tools is the data; this is the one place that
turns "which tools does this role have enabled" into a list, for whoever wires
tool-calling into the orchestrator later (conversation-core agent — NOT this
change; chat/orchestrator.py is out of scope here).
"""
from __future__ import annotations

from kb.models import AgentPrompt, Tool


def enabled_tools_for_role(role: str) -> list[Tool]:
    """Active tools enabled for this role's AgentPrompt, or [] if the role has
    no prompt row or no tools enabled."""
    prompt = AgentPrompt.objects.filter(role=role).first()
    if prompt is None:
        return []
    return list(prompt.tools.filter(is_active=True).order_by("name"))


def tool_enabled(role: str, slug: str) -> bool:
    """True when `slug` is both enabled on this role's AgentPrompt AND its Tool row
    is_active — the two-gate check the orchestrator uses before running any tool
    behavior (today: consult_brand)."""
    return any(t.slug == slug for t in enabled_tools_for_role(role))


def render_tools_block(role: str) -> str:
    """The {tools} prompt placeholder (V2 S9): every enabled+active tool's name and
    description, for the role's prompt to be aware of. Only consult_brand has actual
    orchestrator behavior today (chat/orchestrator.py) — any other enabled tool is
    listed here for visibility only, with no wired handler yet."""
    tools = enabled_tools_for_role(role)
    if not tools:
        return ""
    lines = "\n".join(f"- {t.name}: {t.description}" for t in tools if t.description) or \
        "\n".join(f"- {t.name}" for t in tools)
    return "\n\nTOOLS AVAILABLE TO YOU\n" + lines
