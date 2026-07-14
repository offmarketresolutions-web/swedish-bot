"""Category Q — website form-chip emission (plan S6 / D2, conversation side).

crm.form_buttons picks the active FormButton by case category (quote_request
fallback), respects the outside-area gate, and the orchestrator emits it as a
url-chip at the trigger points (post-lead thanks, service recommendation, explicit
ask). Emission marks the case form_status="shown" and flushes Session.form_*.
The widget's anchor rendering + /api/prefill are the sibling agent's scope — here
we only assert the chip dict shape + tracking.
"""
import pytest

from chat import orchestrator as orch
from chat.casestate import new_case_state
from crm import form_buttons
from crm.models import FormButton, Session

pytestmark = pytest.mark.django_db


def _cs(category=None, subtype=None, service_area="unknown"):
    cs = new_case_state()
    cs["slots"]["category"] = category
    cs["slots"]["subtype"] = subtype
    cs["service_area"] = service_area
    return cs


# ── crm.form_buttons unit behavior ──────────────────────────────────────────

def test_form_chip_shape_for_category(seeded):
    FormButton.objects.create(category_slug="heat_pump", label="Book heat-pump service",
                              url="https://nordlandvvs.se/hp", is_active=True)
    chip = form_buttons.form_chip_for(_cs(category="heat_pump"))
    assert chip == {"value": "open_form", "label": "Book heat-pump service",
                    "url": "https://nordlandvvs.se/hp"}


def test_form_chip_falls_back_to_quote_request(seeded):
    FormButton.objects.create(category_slug="quote_request", label="Request a quote",
                              url="https://nordlandvvs.se/offert", is_active=True)
    # water_filtration has no dedicated button → quote_request fallback
    chip = form_buttons.form_chip_for(_cs(category="water_filtration"))
    assert chip["url"] == "https://nordlandvvs.se/offert"


def test_form_chip_resolves_subtype_leaf_to_family(seeded):
    FormButton.objects.create(category_slug="heat_pump", label="HP", url="https://x/hp")
    # a leaf subtype (water_to_water) resolves up to its heat_pump family
    chip = form_buttons.form_chip_for(_cs(category="water_to_water", subtype="water_to_water"))
    assert chip["url"] == "https://x/hp"


def test_form_chip_suppressed_when_outside_area(seeded):
    FormButton.objects.create(category_slug="heat_pump", label="HP", url="https://x/hp")
    assert form_buttons.form_chip_for(_cs(category="heat_pump", service_area="outside_area")) is None


def test_no_button_no_chip(seeded):
    assert form_buttons.form_chip_for(_cs(category="heat_pump")) is None


# ── orchestrator emission triggers ──────────────────────────────────────────

def _reach_specialist_manual(conv, mock):
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")
    orch.process_turn(conv, "showing alarm H01 5252")
    orch.process_turn(conv, "IVT")
    return orch.process_turn(conv, "Geo 412C")


def test_emission_on_explicit_ask(seeded, mock_gemini):
    FormButton.objects.create(category_slug="heat_pump", label="Book service", url="https://x/hp")
    # Stay in the specialist phase (solve) so the explicit ask is a troubleshooting turn.
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Sure, I can set that up.", "confidence": 0.9,
        "decision": "solve", "in_docs": True, "report": {"resolved": None}}
    conv, _ = orch.open_conversation()
    _reach_specialist_manual(conv, mock_gemini)          # turn 1 solve → "Did that fix it?"
    res = orch.process_turn(conv, "can you help me boka service please")  # explicit ask
    assert any(c.get("value") == "open_form" for c in res["chips"])
    conv.refresh_from_db()
    assert conv.case_state["report"]["form_status"] == "shown"


def test_emission_on_solve_service_severity(seeded, mock_gemini):
    FormButton.objects.create(category_slug="heat_pump", label="Book service", url="https://x/hp")
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "That's a maintenance item — I can arrange a visit.",
        "confidence": 0.9, "decision": "solve", "severity": "service", "in_docs": True,
        "report": {"resolved": None}}
    conv, _ = orch.open_conversation()
    res = _reach_specialist_manual(conv, mock_gemini)
    assert any(c.get("value") == "open_form" for c in res["chips"])


def test_emission_on_post_lead_thanks_and_tracking(seeded, mock_gemini):
    FormButton.objects.create(category_slug="heat_pump", label="Book service",
                              url="https://x/hp", is_active=True)
    # default specialist escalates → full escalation flow
    conv, _ = orch.open_conversation()
    _reach_specialist_manual(conv, mock_gemini)
    orch.process_turn(conv, "skip")            # diag → name
    orch.process_turn(conv, "Ove")
    orch.process_turn(conv, "070-700 10 20")
    orch.process_turn(conv, "skip")            # email
    orch.process_turn(conv, "85234")           # postal → approval
    final = orch.process_turn(conv, "yes_send")   # dispatch → thanks + form chip
    assert any(c.get("value") == "open_form" for c in final["chips"])
    sess = Session.objects.get(conversation=conv)
    assert sess.form_shown is True
    assert sess.form_url == "https://x/hp"
    assert sess.form_category == "heat_pump"


def test_widget_fallback_open_form_text_reply(seeded, mock_gemini):
    FormButton.objects.create(category_slug="heat_pump", label="Book service", url="https://x/hp")
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")       # sets category so the fallback resolves the button
    res = orch.process_turn(conv, "open_form")
    assert "https://x/hp" in res["message"]
    assert res["chips"] == []
