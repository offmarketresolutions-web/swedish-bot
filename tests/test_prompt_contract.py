"""The OUTPUT CONTRACT must survive an owner-edited prompt.

`seed_kb` is deliberately no-clobber for `AgentPrompt.body`, so a deploy never
updates a prompt the owner edited in the dashboard. Without a code-owned addendum a
feature whose contract key was added in code (no_action_needed, consult_web) reads
`data.get(key)` forever against an older body that never emits it — the feature is
silently inert in production while every test passes locally against a fresh seed.
"""
from __future__ import annotations

import re

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
            'true/false and "consult_web": {{"question": "<...>"}} or null. '
            'If the onset is unknown, ask about it first.')
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


# ── Tier-B meta-guard (docs/TEST_STRATEGY.md) ─────────────────────────────────
# The 2026-08-11 bug class: the backend reads data.get(key) from an agent's JSON while
# the prompt for that role never declares the key, so the feature is permanently inert
# and every test still passes. Enumerate the contract per role here; any future key read
# by the orchestrator must be added to this map AND reach the rendered prompt.
CONTRACT_KEYS_BY_ROLE = {
    "specialist": ("answer_to_customer", "confidence", "decision", "in_docs",
                   "no_action_needed"),
    "intelligent_specialist": ("answer_to_customer", "confidence", "decision", "in_docs",
                               "no_action_needed", "consult_web"),
    "heat_pump_specialist": ("answer_to_customer", "confidence", "decision", "in_docs",
                             "no_action_needed", "consult_web"),
    "water_pump_specialist": ("answer_to_customer", "confidence", "decision", "in_docs",
                              "no_action_needed", "consult_web"),
    "water_filtration_specialist": ("answer_to_customer", "confidence", "decision", "in_docs",
                                    "no_action_needed", "consult_web"),
}


@pytest.mark.parametrize("role", sorted(CONTRACT_KEYS_BY_ROLE))
def test_every_contract_key_the_backend_reads_is_declared_to_the_role(role, seeded):
    rendered = prompts.render(role)
    for key in CONTRACT_KEYS_BY_ROLE[role]:
        assert key in rendered, (
            f"{role} is never told to emit {key!r}, but the backend reads it — "
            "the feature behind it is silently inert")


@pytest.mark.parametrize("role", sorted(CONTRACT_KEYS_BY_ROLE))
def test_contract_survives_a_prompt_the_owner_rewrote(role, seeded):
    """Production shape: seed_kb never overwrites an owner-edited body, so the guard above
    must hold even when the stored prompt predates the key entirely."""
    AgentPrompt.objects.filter(role=role).update(
        body="Owner's own rewritten prompt. Answer the customer and return JSON.")
    rendered = prompts.render(role)
    for key in CONTRACT_KEYS_BY_ROLE[role]:
        if key in ("no_action_needed", "consult_web"):   # the code-owned addendum's job
            assert key in rendered, f"{role} lost {key!r} to an owner rewrite"


# ── Gas-safety regression (run100 S009) ────────────────────────────────────────
# Every safety-relevant role sanctioned "switch it off at the main switch" as a
# universally-safe emergency action, with no exception for gas/fuel danger — where
# operating any switch (even OFF) risks an ignition spark. A live conversation
# (persona danger_kind=gas) got exactly that instruction. Pin the gas exception in
# every role that carries the switch-off guidance, plus the SAFETY classifier that
# is supposed to catch it if a role's own instructions fail.
_SWITCH_OFF_ROLES = ("intake", "specialist", "intelligent_intake", "intelligent_specialist",
                    "heat_pump_specialist", "water_pump_specialist",
                    "water_filtration_specialist", "safety")


@pytest.mark.parametrize("role", _SWITCH_OFF_ROLES)
def test_switch_off_guidance_carries_a_gas_exception(role, seeded):
    rendered = prompts.render(role)
    collapsed = re.sub(r"\s+", " ", rendered)  # source wraps "main\nswitch" across lines
    assert "main switch" in collapsed, f"{role} lost the switch-off guidance entirely"
    low = collapsed.lower()
    assert "gas" in low and ("except" in low or "unsafe regardless" in low
                             or "other danger" in low), (
        f"{role} sanctions switching off at the main switch with no visible gas exception — "
        "this produced a live safety defect (run100 S009): a gas-smell scenario got told "
        "to walk to the breaker and flip it, the one thing gas-safety protocol forbids.")


# ── Gas rule is code-owned, not just seeded (the fix for the S009 regression) ──
# The gas exception used to live ONLY in the editable prompt body, and seed_kb is
# no-clobber — so an owner who had already edited a prod prompt (or a body that
# predates the rule) would never receive it. Pin that chat.prompts re-injects the
# rule itself (keyed on the literal absence of the word "ignite") exactly like the
# no_action_needed / consult_web contract addenda already do.

@pytest.mark.parametrize("role", _SWITCH_OFF_ROLES)
def test_owner_rewrite_with_switch_off_still_gets_gas_exception(role, seeded):
    _set_body(role, "Owner's rewritten prompt. If there is danger, tell them to switch it "
                    "off at the main switch, then escalate. Return JSON.")
    rendered = prompts.render(role)
    collapsed = re.sub(r"\s+", " ", rendered).lower()
    assert "ignite" in collapsed, f"{role} owner rewrite never got the gas exception appended"
    assert "gas" in collapsed


@pytest.mark.parametrize("role", _SWITCH_OFF_ROLES)
def test_freshly_seeded_prompts_need_no_safety_addendum(role, seeded):
    """The repo defaults already carry the gas exception (and therefore 'ignite') — the
    SAFETY addendum is a safety net for stale/owner-edited bodies, not a second source
    of truth that could drift from seed_prompts.py, and must never duplicate the text."""
    assert "SAFETY (required by the backend)" not in prompts.render(role)


def test_specialists_are_required_to_establish_onset_before_a_comfort_verdict():
    """Spec §7: "The system must distinguish between: 1. A condition that has always
    existed or has developed gradually. 2. A sudden change after the system previously
    worked normally." That distinction decides whether a documented customer setting is
    appropriate (§7) or service should be offered (§8).

    Across 100 live conversations onset was never captured in 67, and in 32 of those the
    customer was reporting a comfort/heat problem — so the specialist could not apply the
    rule at all and defaulted to escalating. Nothing ever ASKS: onset is only extracted
    opportunistically when a customer happens to volunteer it.

    Code-owned because seed_kb is no-clobber: an already-seeded prompt would never get it."""
    from chat.prompts import contract_addendum

    body = "You are a specialist. Return JSON."
    add = contract_addendum("specialist", body)
    assert "onset" in add, add
    assert "suddenly" in add.lower() and "always" in add.lower(), add

    # Already declared in the body -> not duplicated. Keyed on the specific rule
    # ("onset is unknown"), not the bare word: every seeded body mentions "onset" for
    # fact extraction while saying nothing about ASKING for it.
    assert "onset" not in contract_addendum("specialist", body + " If the onset is unknown, ask.")

    # General (no-manual) specialists need it too — §7 covers both.
    from chat.prompts import _GENERAL_ROLES
    for role in _GENERAL_ROLES:
        assert "onset" in contract_addendum(role, body), role


def test_the_onset_ask_actually_reaches_a_rendered_specialist_prompt(seeded):
    """contract_addendum() returning the text is not the same as the agent receiving it —
    render() interpolates and can swallow content. This asserts the integration point,
    against a DB body seeded BEFORE the rule existed, which is what every already-deployed
    install looks like."""
    from chat import prompts

    for role in ("specialist", "heat_pump_specialist", "water_pump_specialist",
                 "water_filtration_specialist", "intelligent_specialist"):
        out = prompts.render(role, locale="sv", brand="IVT", model="Geo 412C",
                             category="heat_pump", brand_notes="", faq="", general_knowledge="",
                             problem="kallt", error_code="", forced_wrapup="false",
                             previous_checks="", onset="", common_issues="", tools="",
                             consult_notes="")
        # Two wordings carry this rule: the seeded ONSET RULES block (fresh installs) and
        # the contract addendum (installs seeded before the rule existed). Assert the part
        # they share, so the test holds in BOTH states rather than pinning one of them.
        # Whitespace-normalised: the seeded block is hard-wrapped, so "ask ONE short
        # question" spans a line break there and would never match literally.
        flat = " ".join(out.split())
        assert "ask ONE short question" in flat, role
        assert "suddenly after working normally" in flat, role
