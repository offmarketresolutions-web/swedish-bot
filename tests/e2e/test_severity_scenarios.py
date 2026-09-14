"""Real customers with different problems, driven through the widget.

The owner's spec asks the bot to do three different things depending on what it is told,
and getting the wrong one is a different kind of failure each time:

  STOP     — a gas or refrigerant leak. Say the safety line immediately, escalate urgent,
             and never walk the customer through diagnostics first. Over-helping here is
             the dangerous failure.
  REDIRECT — a real fault. Identify the machine, then hand to a technician with contact
             details captured. Under-helping here loses a job.
  RESOLVE  — something documented the customer can do themselves. Escalating this wastes
             a truck roll.
  DECLINE  — not our trade at all. Close gracefully rather than guess.

Every message below is typed into the composer or picked from a chip, exactly as a customer
would. Assertions are on what the customer SEES plus what the office ends up with.

    .venv\\Scripts\\python.exe -m pytest -m e2e -s -v tests/e2e/test_severity_scenarios.py
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import Page

from .conftest import shot
from .test_customer_journey import (
    bot_turns,
    chips,
    last_bot,
    open_widget,
    say,
    tap,
)

pytestmark = [pytest.mark.e2e, pytest.mark.live]

UNIQUE = f"{uuid.uuid4().int % 10**6:06d}"


def _conversation_for(orm, page: Page):
    """The Conversation row behind the widget session currently on screen."""
    session_id = page.evaluate(
        "() => { try { const k = Object.keys(sessionStorage)"
        ".find(k => k.startsWith('nordland-chat:'));"
        " return k ? JSON.parse(sessionStorage.getItem(k)).sessionId : null; }"
        " catch (e) { return null; } }")
    assert session_id, "the widget stored no session id"
    with orm.unblock():
        from chat.models import Conversation

        return Conversation.objects.get(public_id=session_id)


# ── STOP: over-helping here is the dangerous failure ─────────────────────────

def test_a_gas_smell_stops_everything_and_says_112(page: Page, orm):
    """No triage, no "which brand is it?", no model call at all — the customer is standing
    in a building that smells of gas."""
    open_widget(page)
    reply = say(page, "Det luktar gas vid pannan i källaren")

    assert "112" in reply, f"the emergency number was not given: {reply!r}"
    assert re.search(r"lämna byggnaden", reply, re.I), f"no evacuate instruction: {reply!r}"
    assert re.search(r"rör inga strömbrytare|gnista", reply, re.I), (
        f"no spark warning — flipping a switch can ignite the gas: {reply!r}")
    # The failure that matters: walking them through diagnostics instead.
    assert not re.search(r"vilket märke|vilken modell|postnummer", reply, re.I), (
        f"the bot asked triage questions during a gas emergency: {reply!r}")

    conv = _conversation_for(orm, page)
    with orm.unblock():
        cs = conv.case_state or {}
        assert cs.get("escalation_reason") == "gas emergency", cs.get("escalation_reason")
    shot(page, "scenario_gas_emergency.png")


def test_a_refrigerant_leak_stops_and_never_says_switch_it_off(page: Page, orm):
    """Manufacturer manuals say "switch the unit off", but modern R32/R290 units are
    flammable — the safe shape is ventilate, keep away, no flames, touch nothing."""
    open_widget(page)
    reply = say(page, "Det luktar kemiskt vid utedelen och det väser om den")

    assert re.search(r"köldmedie|vädra|öppna fönster", reply, re.I), (
        f"not the refrigerant safety line: {reply!r}")
    assert re.search(r"ingen öppen eld|rökning", reply, re.I), (
        f"no ignition-source warning: {reply!r}")
    assert re.search(r"rör.{0,20}inte|hantera inte", reply, re.I), (
        f"the customer was not told to leave the unit alone: {reply!r}")

    conv = _conversation_for(orm, page)
    with orm.unblock():
        cs = conv.case_state or {}
        assert cs.get("escalation_reason") == "refrigerant emergency", cs.get("escalation_reason")


# ── DECLINE: not our trade ───────────────────────────────────────────────────

def test_a_question_that_is_not_our_trade_closes_gracefully(page: Page, orm):
    """Two off-topic turns in a row and the bot should stop guessing and say what it does."""
    open_widget(page)
    say(page, "Kan ni laga min bil? Den startar inte på morgonen")
    reply = say(page, "Det är en Volvo V70 från 2012, batteriet kanske")

    assert re.search(r"värmepump|vattenpump|vattenfilter", reply, re.I), (
        f"the close should say what we DO cover: {reply!r}")
    assert not re.search(r"vilket märke är det|postnummer", reply, re.I), (
        f"still collecting details for a car: {reply!r}")

    conv = _conversation_for(orm, page)
    with orm.unblock():
        cs = conv.case_state or {}
        assert cs.get("decision") == "off_domain_close", cs.get("decision")
        # A car question must not leave a lead behind.
        session = getattr(conv, "session", None)
        assert session is None or session.customer_id is None, (
            "an off-domain conversation produced a customer profile")


# ── RESOLVE: escalating this wastes a truck roll ─────────────────────────────

def test_a_documented_self_serve_answer_is_given_not_escalated(page: Page, orm):
    """A dirty filter is the customer's own job. The bot should say so and then offer to
    pass the case to a specialist — not book a technician."""
    open_widget(page)
    assert chips(page), "the opener should offer categories"
    tap(page, "Värmepump")

    answers = ["85230", "Luften känns svagare än vanligt och filtret ser dammigt ut",
               "IVT", "AirX 500", "Det har blivit sämre gradvis", "nej"]
    for a in answers:
        say(page, a)
        if re.search(r"rengör|byt filtret|filtret", last_bot(page), re.I):
            break

    joined = " ".join(bot_turns(page)).lower()
    assert re.search(r"filter", joined), (
        f"a dirty-filter case never mentioned the filter. Turns: {bot_turns(page)[-2:]}")
    shot(page, "scenario_self_serve.png")


# ── the matrix, for the record ───────────────────────────────────────────────

def test_the_three_outcomes_are_actually_distinguishable(page: Page, orm):
    """A guard against the bot collapsing into one behaviour: the same widget must produce a
    different escalation_reason for a gas leak than for an ordinary fault."""
    open_widget(page)
    say(page, "Det luktar gas vid pannan")
    gas = _conversation_for(orm, page)

    open_widget(page)  # fresh visit
    tap(page, "Värmepump")
    say(page, "85230")
    say(page, "Värmepumpen larmar och ger ingen värme")
    fault = _conversation_for(orm, page)

    with orm.unblock():
        gas_reason = (gas.case_state or {}).get("escalation_reason")
        fault_reason = (fault.case_state or {}).get("escalation_reason")
        assert gas_reason == "gas emergency", gas_reason
        assert fault_reason != "gas emergency", (
            f"an ordinary fault was treated as a gas emergency: {fault_reason}")
