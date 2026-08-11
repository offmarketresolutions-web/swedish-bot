"""Gate audit (2026-08-11): fail-silent gates found during a sweep of
kb/models.py + crm/geo.py + crm/form_buttons.py + chat/prompts.py gates.

1. chat.prompts.render() with a missing/inactive AgentPrompt row must never hand
   the model an unguided system instruction (no persona, no safety rules) — that
   is a real safety hole, not a graceful "feature off".
2. crm.form_buttons.form_chip_for() must never emit a chip whose url is blank —
   FormButton rows are auto-created by the dashboard with url="" (see
   dashboard/views.py) and is_active=True by model default, so this fires the
   moment an owner hasn't filled the URL in yet, i.e. exactly the fresh-install
   default.
"""
from __future__ import annotations

import pytest
from django.core.management import call_command

from chat import prompts
from crm.form_buttons import form_chip_for
from crm.models import FormButton
from kb.models import AgentPrompt

pytestmark = pytest.mark.django_db


def test_render_with_inactive_agent_does_not_produce_unguided_prompt():
    call_command("seed_kb")
    p = AgentPrompt.objects.filter(role="specialist").first()
    assert p is not None
    p.is_active = False
    p.save()

    system = prompts.render("specialist", locale="sv", brand="Bosch", model="X1")

    # An unguided call has no persona/safety content at all -- only the code-owned
    # OUTPUT CONTRACT addendum survives when body="". That must not happen: render()
    # must fall back to a safe minimal persona/safety body, not silence.
    assert "You are" in system or "Nordland" in system


def test_render_with_missing_agent_role_does_not_produce_unguided_prompt():
    # No seed at all -> AgentPrompt.objects for this role is empty.
    system = prompts.render("specialist", locale="sv", brand="Bosch", model="X1")
    assert "You are" in system or "Nordland" in system


def test_form_chip_for_never_emits_blank_url():
    call_command("seed_kb")
    FormButton.objects.create(
        category_slug="quote_request", label="Get a quote", url="", is_active=True)

    chip = form_chip_for({"slots": {"category": "heat_pump"}})

    assert chip is None or chip.get("url")
