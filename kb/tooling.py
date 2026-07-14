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
