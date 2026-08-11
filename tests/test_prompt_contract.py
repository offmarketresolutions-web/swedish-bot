"""The OUTPUT CONTRACT must survive an owner-edited prompt.

`seed_kb` is deliberately no-clobber for `AgentPrompt.body`, so a deploy never
updates a prompt the owner edited in the dashboard. Without a code-owned addendum a
feature whose contract key was added in code (no_action_needed, consult_web) reads
`data.get(key)` forever against an older body that never emits it — the feature is
silently inert in production while every test passes locally against a fresh seed.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from chat import prompts
from kb.models import AgentPrompt

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _set_body(role: str, body: str) -> None:
    AgentPrompt.objects.update_or_create(
        role=role, defaults={"body": body, "language_directive": "", "is_active": True})


def test_stale_specialist_prompt_still_gets_no_action_needed(seeded):
    _set_body("specialist", "You are the specialist. Return JSON with decision and confidence.")
    out = prompts.render("specialist")
    assert "no_action_needed" in out
    assert "OUTPUT CONTRACT (required by the backend)" in out


def test_stale_general_prompt_gets_both_keys(seeded):
    _set_body("heat_pump_specialist", "You are the heat pump specialist. Return JSON.")
    out = prompts.render("heat_pump_specialist")
    assert "no_action_needed" in out
    assert "consult_web" in out


def test_manual_specialist_never_offered_consult_web(seeded):
    """consult_web is a no-manual tool; the manual-mode specialist must not be told it exists."""
    _set_body("specialist", "You are the specialist. Return JSON.")
    out = prompts.render("specialist")
    assert "consult_web" not in out


def test_addendum_not_duplicated_when_body_already_declares_keys(seeded):
    body = ('You are the heat pump specialist. Return JSON with "no_action_needed": '
            'true/false and "consult_web": {{"question": "<...>"}} or null.')
    _set_body("heat_pump_specialist", body)
    out = prompts.render("heat_pump_specialist")
    assert "OUTPUT CONTRACT (required by the backend)" not in out
    assert out.count("no_action_needed") == 1


def test_freshly_seeded_prompts_need_no_addendum(seeded):
    """The repo defaults already carry both keys — the addendum is a safety net, not
    a second source of truth that could drift from seed_prompts.py."""
    for role in ("specialist", "intelligent_specialist", "heat_pump_specialist",
                 "water_pump_specialist", "water_filtration_specialist"):
        agent = AgentPrompt.objects.filter(role=role).first()
        assert agent, role
        assert prompts.contract_addendum(role, agent.body) == "", role


def test_addendum_survives_placeholder_formatting(seeded):
    """render() runs format_map over body+addendum; the consult_web example contains
    braces, so it must be escaped ({{ }}) or templating would blow up or eat it."""
    _set_body("water_pump_specialist", "Specialist. {problem} Return JSON.")
    out = prompts.render("water_pump_specialist", problem="no water")
    assert "no water" in out
    assert '"question"' in out          # brace-escaped example survived format_map
    assert "{{" not in out
