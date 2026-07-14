"""Installation address at handoff (feature 2): after the postcode, the escalation
contact flow asks the installation street address as the LAST question before the
send-approval step. Skippable exactly like email; persisted to Customer.address; rides
the lead payload; an already-known (returning-customer) address is not re-asked.
"""
import pytest
from django.core.management import call_command

from chat import orchestrator as orch
from chat.casestate import CONTACT_SLOTS
from crm.models import Customer, ServiceRequest, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_address_is_last_contact_slot():
    assert CONTACT_SLOTS == ["name", "phone", "email", "postal_code", "address"]


def _escalate(conv, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "not sure", "confidence": 0.3, "decision": "escalate",
        "in_docs": False, "report": {}}
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")        # postcode declined early
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    orch.process_turn(conv, "IVT 490")   # → escalate → diag prompt
    orch.process_turn(conv, "rattles")   # diag → name


def test_full_flow_asks_address_after_postal_and_persists(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _escalate(conv, mock_gemini)
    orch.process_turn(conv, "Jane Tester")      # name → phone
    orch.process_turn(conv, "070-1234567")      # phone → email
    orch.process_turn(conv, "skip")             # email → postal
    addr_q = orch.process_turn(conv, "98101")   # postal → address question
    assert "address" in addr_q["message"].lower()
    approval = orch.process_turn(conv, "Storgatan 5")  # address → approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    assert "Storgatan 5" in approval["message"]
    orch.process_turn(conv, "yes_send")
    sess = Session.objects.get(conversation=conv)
    assert sess.customer.address == "Storgatan 5"
    sr = ServiceRequest.objects.get(session=sess)
    assert sr.payload_json["customer"]["address"] == "Storgatan 5"


def test_address_is_skippable_and_never_blocks_lead(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _escalate(conv, mock_gemini)
    orch.process_turn(conv, "Jane Tester")      # name → phone
    orch.process_turn(conv, "070-1234567")      # phone → email
    orch.process_turn(conv, "skip")             # email → postal
    orch.process_turn(conv, "98101")            # postal → address
    approval = orch.process_turn(conv, "skip")  # address declined → approval (not blocked)
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    assert "Storgatan" not in approval["message"]  # no address → no summary line
    done = orch.process_turn(conv, "yes_send")
    assert "Nordland" in done["message"]
    sess = Session.objects.get(conversation=conv)
    assert sess.customer.address == ""          # declined → blank, lead still dispatched
    assert ServiceRequest.objects.filter(session=sess).exists()


def test_returning_customer_skips_known_address(seeded, mock_gemini):
    # a returning customer (phone hash + name match) with an address on file is not re-asked
    Customer.objects.create(name="Jane Tester", phone="+46701234567",
                            address="Gamla Vägen 3", consent_to_contact=True)
    conv, _ = orch.open_conversation()
    _escalate(conv, mock_gemini)
    orch.process_turn(conv, "Jane Tester")      # name → phone
    orch.process_turn(conv, "070-1234567")      # phone → email (returning detected)
    orch.process_turn(conv, "skip")             # email → postal
    approval = orch.process_turn(conv, "98101")  # postal → (address skipped) → approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    assert "Gamla Vägen 3" in approval["message"]  # known address echoed, not re-asked
    orch.process_turn(conv, "yes_send")
    sess = Session.objects.get(conversation=conv)
    assert sess.customer.address == "Gamla Vägen 3"
