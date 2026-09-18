"""Category P — service-area conversation hooks (plan S5 / D2).

Gate runs at LEAD time only (never blocks troubleshooting):
  inside  → escalate normally, status rides the lead.
  border  → escalate + "technician confirms coverage" line.
  outside → ask ONCE about a previous installer; a listed installer upgrades to
            inside; otherwise polite decline (no lead, no form), state RESOLVED.
  dormant (GeoSettings off) → behaves exactly as before.
"""
import pytest

from chat import orchestrator as orch
from crm.models import FormButton, GeoSettings, PostcodeArea, ServiceArea, ServiceRequest

pytestmark = pytest.mark.django_db

# A square inside-area around Sundsvall (lng 17.0–17.6, lat 62.2–62.6), border_km=10.
SQUARE = [[17.0, 62.2], [17.6, 62.2], [17.6, 62.6], [17.0, 62.6], [17.0, 62.2]]


@pytest.fixture
def geo_configured(seeded):
    """Enabled GeoSettings + one inside ServiceArea + three postcodes (inside / border /
    far outside). FormButton so the outside-gate suppression is observable."""
    ServiceArea.objects.create(name="Sundsvall core", kind="inside",
                               polygon={"type": "Polygon", "coordinates": [SQUARE]}, border_km=10.0)
    PostcodeArea.objects.create(code="85234", lat=62.40, lng=17.30, city="Sundsvall")   # inside
    PostcodeArea.objects.create(code="86040", lat=62.40, lng=17.66, city="Edge")        # ~2–3 km outside → border
    PostcodeArea.objects.create(code="11122", lat=59.33, lng=18.06, city="Stockholm")   # far outside
    cfg = GeoSettings.load()
    cfg.enabled = True
    cfg.fallback_contact_url = "https://nordlandvvs.se/kontakt"
    cfg.save()
    FormButton.objects.create(category_slug="heat_pump", label="Book heat-pump service",
                              url="https://nordlandvvs.se/offert", is_active=True)


def _drive_to_escalation(conv, mock, postcode):
    """Intake with a real postcode → general specialist → escalate (default mock).
    NIBE heat pump → the heat_pump_specialist general role (feature 1 split)."""
    mock.responses["heat_pump_specialist"] = {
        "answer_to_customer": "I'll get a Nordland technician to look at your heat pump.",
        "confidence": 0.0, "decision": "escalate", "in_docs": False, "report": {}}
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, postcode)
    orch.process_turn(conv, "my heat pump is not heating properly")
    orch.process_turn(conv, "NIBE")            # non-catalog brand → general mode
    res = orch.process_turn(conv, "unknown")   # no model → general specialist → escalate
    return res


def test_inside_area_escalates_and_rides_lead(geo_configured, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_escalation(conv, mock_gemini, "85234")
    conv.refresh_from_db()
    assert conv.case_state["service_area"] == "inside_area"
    # No installer question — inside proceeds straight to the diag/contact flow.
    # (postcode 85234 was captured early → the contact postal slot is auto-filled/skipped)
    orch.process_turn(conv, "skip")            # diag → name
    orch.process_turn(conv, "Ove")
    orch.process_turn(conv, "070-700 10 20")
    orch.process_turn(conv, "skip")            # email → address (postal auto-filled)
    orch.process_turn(conv, "skip")            # address → approval
    orch.process_turn(conv, "yes_send")        # dispatch
    sr = ServiceRequest.objects.get(session__conversation=conv)
    assert sr.payload_json["service_area"]["status"] == "inside_area"


def test_border_area_adds_coverage_line(geo_configured, mock_gemini):
    conv, _ = orch.open_conversation()
    res = _drive_to_escalation(conv, mock_gemini, "86040")
    conv.refresh_from_db()
    assert conv.case_state["service_area"] == "border_review"
    assert "confirm coverage" in res["message"].lower()


def test_outside_with_listed_installer_upgrades_to_inside(geo_configured, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_escalation(conv, mock_gemini, "11122")
    conv.refresh_from_db()
    assert conv.case_state.get("awaiting_installer") is True     # asked once
    res = orch.process_turn(conv, "yes")
    assert "which" in res["message"].lower()
    res = orch.process_turn(conv, "Bylunds VVS")                 # a listed previous installer
    conv.refresh_from_db()
    assert conv.case_state["service_area"] == "inside_area"
    # now proceeds into the normal escalation flow (diag prompt), NOT a decline
    assert conv.case_state["state"] == "ESCALATE"


def test_outside_no_installer_declines_no_lead_no_form(geo_configured, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_escalation(conv, mock_gemini, "11122")
    orch.process_turn(conv, "yes")
    res = orch.process_turn(conv, "Some Random Plumber AB")      # NOT a listed installer
    conv.refresh_from_db()
    assert conv.case_state["state"] == "RESOLVED"
    assert conv.case_state["service_area"] == "outside_area"
    assert res["chips"] == []                                    # no form chip
    assert "https://nordlandvvs.se/kontakt" in res["message"]   # fallback link offered
    assert not ServiceRequest.objects.filter(session__conversation=conv).exists()


def test_outside_direct_no_declines(geo_configured, mock_gemini):
    conv, _ = orch.open_conversation()
    _drive_to_escalation(conv, mock_gemini, "11122")
    res = orch.process_turn(conv, "no")                          # no previous installer
    conv.refresh_from_db()
    assert conv.case_state["state"] == "RESOLVED"
    assert not ServiceRequest.objects.filter(session__conversation=conv).exists()
    assert "service area" in res["message"].lower() or "arbetsområde" in res["message"].lower()


def test_late_postcode_outside_area_then_declined_consent_still_suppresses_form(
        geo_configured, mock_gemini):
    """GAP #5 fix MUST NOT BREAK the out-of-area suppression: the escalate-decision and
    declined-consent chokepoints both now set cs["_emit_form"]=True unconditionally, but
    crm.form_buttons.form_button_for() still gates on service_area=="outside_area" at
    emission time — so a customer who is only discovered to be outside the area once the
    postcode is captured at the CONTACT stage (S003 late-postcode path) must still see no
    form chip, whether they grant or decline consent."""
    mock_gemini.responses["heat_pump_specialist"] = {
        "answer_to_customer": "I'll get a Nordland technician to look at your heat pump.",
        "confidence": 0.0, "decision": "escalate", "in_docs": False, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")                      # early postcode ask declined
    orch.process_turn(conv, "my heat pump is not heating properly")
    orch.process_turn(conv, "NIBE")
    orch.process_turn(conv, "unknown")                 # → general specialist → escalate
    orch.process_turn(conv, "no error code")           # diag step
    orch.process_turn(conv, "Kim Test")                # name
    orch.process_turn(conv, "070-123 45 67")           # phone
    orch.process_turn(conv, "skip")                    # email
    orch.process_turn(conv, "11122")                   # postcode, late — far outside
    orch.process_turn(conv, "skip")                    # address → approval
    res = orch.process_turn(conv, "no")                # declines consent
    conv.refresh_from_db()
    assert conv.case_state["service_area"] == "outside_area"
    assert res["chips"] == []                          # no form chip despite _emit_form=True


def test_dormant_geo_behaves_as_before(seeded, mock_gemini):
    """GeoSettings disabled (default) → the gate is a no-op: no installer question,
    normal escalation, lead created."""
    PostcodeArea.objects.create(code="11122", lat=59.33, lng=18.06, city="Stockholm")
    conv, _ = orch.open_conversation()
    _drive_to_escalation(conv, mock_gemini, "11122")
    conv.refresh_from_db()
    assert conv.case_state.get("awaiting_installer") is not True
    assert conv.case_state["service_area"] == "unknown"          # never resolved
    orch.process_turn(conv, "skip")
    orch.process_turn(conv, "Ove")
    orch.process_turn(conv, "070-700 10 20")
    orch.process_turn(conv, "skip")            # email → address (postal 11122 auto-filled)
    orch.process_turn(conv, "skip")            # address → approval
    orch.process_turn(conv, "yes_send")
    assert ServiceRequest.objects.filter(session__conversation=conv).exists()


def test_late_postcode_given_at_contact_stage_still_reaches_the_lead(geo_configured, mock_gemini):
    """Live geo run (S003, 2026-09-02): the emergency path — and any customer who declines the
    early postcode ask — only gives the postcode at CONTACT stage. The gate reads
    slots.postal_code, so it saw nothing, and the lead went out with NO postcode and NO area
    status for a Stockholm address. The late postcode must be mirrored into the slots (so it
    flushes to the Session) and the preliminary area status computed for the office to triage.
    No decline this late: the customer has already given name and phone, and an emergency
    lead must never be blocked on geography."""
    mock_gemini.responses["heat_pump_specialist"] = {
        "answer_to_customer": "I'll get a Nordland technician to look at your heat pump.",
        "confidence": 0.0, "decision": "escalate", "in_docs": False, "report": {}}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")                      # early postcode ask declined
    orch.process_turn(conv, "my heat pump is not heating properly")
    orch.process_turn(conv, "NIBE")
    orch.process_turn(conv, "unknown")                 # → general specialist → escalate
    orch.process_turn(conv, "no error code")           # diag step
    orch.process_turn(conv, "Kim Test")                # name
    orch.process_turn(conv, "070-123 45 67")           # phone
    orch.process_turn(conv, "skip")                    # email
    orch.process_turn(conv, "11122")                   # postcode, late — far outside
    orch.process_turn(conv, "skip")                    # address
    orch.process_turn(conv, "yes_send")
    conv.refresh_from_db()
    sess = conv.session
    assert sess.postal_code == "11122"
    assert sess.service_area_status == "outside_area"
    assert ServiceRequest.objects.filter(session=sess).exists()   # still a lead — office triages
