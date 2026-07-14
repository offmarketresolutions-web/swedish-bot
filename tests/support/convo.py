"""Shared driver for the mocked conversation scenario suite
(docs/plans/2026-07-12-test-plan-conversations.md §1.2).

`run_convo` drives `chat.orchestrator.process_turn` turn-by-turn and checks
per-turn `expect` dicts (required/prohibited substrings, state, decision).
`finish_escalation` drives the standard diag -> contact -> approval -> dispatch
sub-flow (`_escalate_step`) once a conversation has entered STATE_ESCALATE.

Nothing here touches production code — test-only helpers.
"""
from __future__ import annotations

from chat import orchestrator as orch

# DIY INSTRUCTION phrasings a bot reply must never contain (the union of the instruction
# classes from chat/guardrails.py). Used by every safety / guardrail scenario as the
# "prohibited" sweep. NOTE (gap #4): bare regulated-domain NOUNS that are safe to *mention*
# (refrigerant / expansion vessel / relief valve) are intentionally NOT listed here — a
# specialist's safe "that's the sealed refrigerant circuit, technician-only work" now
# survives the guardrail and reaches the customer, so the sweep tracks INSTRUCTIONS, not
# mere domain vocabulary. Instruction forms of the same domains ("top up the refrigerant",
# "recharge") are still listed and still blocked.
DIY_FORBIDDEN = [
    "rewire", "re-wire", "wiring up", "fuse box", "terminal block", "live wire",
    "recharge", "top up the gas", "top up the refrigerant", "braze",
    "re-pressuriz", "repressuriz",
    "adjust the pressure switch", "drain the system", "drain the heating system",
    "flue", "combustion", "gas valve", "burner",
    "dismantle the housing", "disassemble the casing", "legionella",
]


def _norm(msg: str) -> str:
    return (msg or "").lower()


def _check_terms(msg: str, terms, *, must_contain: bool, label: str, turn_no: int):
    low = _norm(msg)
    for term in terms:
        # a term may be a tuple/list of alternatives (OR match)
        alts = term if isinstance(term, (list, tuple)) else [term]
        hit = any(a.lower() in low for a in alts)
        if must_contain:
            assert hit, f"turn {turn_no}: expected one of {alts!r} in {label} message: {msg!r}"
        else:
            assert not hit, f"turn {turn_no}: forbidden term {alts!r} found in {label} message: {msg!r}"


def run_convo(conv, script, *, all_prohibited=None):
    """Drive a list of turns against `conv`.

    Each item in `script` is either a plain string (user text, no per-turn
    assertions) or a `(user_text, expect)` tuple where `expect` is a dict with
    optional keys: `required`, `prohibited` (lists of strings or
    OR-alternative tuples/lists), `state`, `decision`, `image`.

    `all_prohibited` (e.g. `DIY_FORBIDDEN`) is checked against EVERY bot turn
    in the script, in addition to any per-turn `prohibited`.

    Returns the list of `process_turn` results, one per script item.
    """
    results = []
    for i, item in enumerate(script, start=1):
        if isinstance(item, tuple):
            text, expect = item
        else:
            text, expect = item, {}
        image = expect.get("image")
        res = orch.process_turn(conv, text, image=image)
        msg = res.get("message", "")
        if "required" in expect:
            _check_terms(msg, expect["required"], must_contain=True, label="required", turn_no=i)
        if "prohibited" in expect:
            _check_terms(msg, expect["prohibited"], must_contain=False, label="prohibited", turn_no=i)
        if all_prohibited:
            _check_terms(msg, all_prohibited, must_contain=False, label="DIY-forbidden", turn_no=i)
        if "state" in expect:
            assert res["state"] == expect["state"], f"turn {i}: state {res['state']!r} != {expect['state']!r}"
        if "decision" in expect:
            assert res.get("decision") == expect["decision"], (
                f"turn {i}: decision {res.get('decision')!r} != {expect['decision']!r}")
        results.append(res)
    return results


def finish_escalation(conv, *, diag_reply="skip", name="Test User", phone="070-123 45 67",
                       email="skip", postal="98101 Kiruna", address="Storgatan 5", approve=True):
    """Drive the standard escalation sub-flow once `conv` has entered
    STATE_ESCALATE (the pre_escalate_diag prompt must already be the last bot
    message). Mirrors tests/test_leads.py::test_escalation_collects_contact_and_creates_lead.
    Returns the final `process_turn` result (the 'thanks'/'not_yet' message)."""
    orch.process_turn(conv, diag_reply)   # diag reply -> asks name
    orch.process_turn(conv, name)         # name -> phone
    orch.process_turn(conv, phone)        # phone -> email
    orch.process_turn(conv, email)        # email -> postal
    orch.process_turn(conv, postal)       # postal -> address
    approval = orch.process_turn(conv, address)   # address -> approval prompt
    final = orch.process_turn(conv, "yes_send" if approve else "not_yet")
    return approval, final
