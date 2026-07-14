"""Category F -- escalation / callback mechanics (test plan §Category F, F1-F4).
CONTACT_SLOTS sanitizers, approval regex, returning-customer detection, lead
payload completeness.
"""
import pytest

from chat import orchestrator as orch
from crm import leads
from crm.models import Customer, LeadDelivery, ServiceRequest, Session

pytestmark = pytest.mark.django_db


def _to_unsupported_escalation(conv, mock_gemini):
    """Cheapest path into ESCALATE: a non-catalog brand in a serviced family -> general
    specialist -> escalate (reuses C1's setup)."""
    mock_gemini.responses["intelligent_specialist"] = {
        "decision": "escalate", "severity": "normal",
        "answer_to_customer": "I'll get a Nordland technician to help.",
    }
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early (S2) -- declined
    orch.process_turn(conv, "no heat at all")
    orch.process_turn(conv, "other")
    res = orch.process_turn(conv, "Some Unlisted Brand X1")
    assert res["decision"] == "escalate"


# F1 -- full contact capture, clean happy path
def test_f1_full_contact_capture_clean(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    orch.process_turn(conv, "skip")                     # diag -> name
    orch.process_turn(conv, "Lena Nystrom")              # name -> phone
    orch.process_turn(conv, "070-123 45 67")             # phone -> email (E.164 normalize)
    orch.process_turn(conv, "lena@example.se")           # email -> postal
    orch.process_turn(conv, "114 35 Stockholm")          # postal -> address
    approval = orch.process_turn(conv, "Kungsgatan 1")   # address -> approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    done = orch.process_turn(conv, "yes")                # affirmative word (not just the chip)
    assert "Nordland" in done["message"] and "Lena" in done["message"]

    sess = Session.objects.get(conversation=conv)
    assert sess.customer.name == "Lena Nystrom"
    assert sess.customer.phone == "+46701234567"
    assert sess.customer.email == "lena@example.se"
    assert sess.customer.postal_code
    sr = ServiceRequest.objects.get(session=sess)
    for field in ("name", "phone", "email", "postal_code"):
        assert sr.payload_json["customer"].get(field)
    assert LeadDelivery.objects.get(service_request=sr, sink="db").status == "success"
    sr2, _ = leads.create_and_dispatch(sess, sr.escalation_reason)
    assert sr2.pk == sr.pk  # idempotency_key is stable on replay


# F2a -- refuses phone, gives email instead -> lead still created (email only)
def test_f2a_refuses_phone_gives_email(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    orch.process_turn(conv, "skip")                # diag -> name
    orch.process_turn(conv, "Kim")                  # name -> phone
    orch.process_turn(conv, "I'd rather not give my number")  # invalid -> reask_phone
    res = orch.process_turn(conv, "no")             # decline phone -> email
    assert "email" in res["message"].lower() or "e-post" in res["message"].lower()
    orch.process_turn(conv, "kim@example.se")        # email -> postal
    orch.process_turn(conv, "skip")                  # postal skipped -> address
    approval = orch.process_turn(conv, "skip")       # address skipped -> approval
    done = orch.process_turn(conv, "yes_send")
    assert "Nordland" in done["message"]

    sess = Session.objects.get(conversation=conv)
    assert not sess.customer.phone
    assert sess.customer.email == "kim@example.se"
    assert ServiceRequest.objects.filter(session=sess).exists()


# F2b -- refuses ALL contact -> graceful close, no lead, no junk customer
def test_f2b_refuses_all_contact_no_lead(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    orch.process_turn(conv, "no")   # diag -> name
    orch.process_turn(conv, "no")   # name declined -> phone
    orch.process_turn(conv, "no")   # phone declined -> email
    orch.process_turn(conv, "no")   # email declined -> postal
    orch.process_turn(conv, "no")   # postal declined -> address
    orch.process_turn(conv, "no")   # address declined -> "need a phone" gate
    final = orch.process_turn(conv, "no")  # still declines -> graceful close
    assert "website" in final["message"].lower()
    assert ServiceRequest.objects.count() == 0
    assert not Customer.objects.filter(name="no").exists()
    assert not Customer.objects.filter(phone__in=("no", "")).exists()


# F3 -- requesting a specific callback time (captured, never guaranteed)
def test_f3_preferred_callback_time_captured_not_promised(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    # the diag reply is where free-text context (like a time preference) is captured
    orch.process_turn(conv, "can they call me tomorrow after 5pm? no error code to report")
    orch.process_turn(conv, "Bjorn")
    orch.process_turn(conv, "070-200 30 40")
    orch.process_turn(conv, "skip")               # email -> postal
    orch.process_turn(conv, "skip")               # postal -> address
    approval = orch.process_turn(conv, "skip")    # address -> approval
    done = orch.process_turn(conv, "yes_send")
    assert "booked" not in done["message"].lower()
    assert "confirmed for" not in done["message"].lower()
    sess = Session.objects.get(conversation=conv)
    sr = ServiceRequest.objects.get(session=sess)
    assert "5pm" in str(sr.payload_json).lower() or "5pm" in (sess.conversation.case_state["slots"].get("problem") or "").lower()


# F4 -- existing-customer recognition (returning caller)
def test_f4_returning_customer_recognized_and_greeted(seeded, mock_gemini):
    """The `welcome_back` greeting + `CaseState.returning` flag both work correctly
    -- see the separate xfail below for the linkage gap this uncovered."""
    from crm.models import phone_hash

    Customer.objects.create(name="Asa Prior", phone="+46709998877",
                            phone_hash=phone_hash("+46709998877"), consent_to_contact=True)
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    orch.process_turn(conv, "skip")           # diag -> name
    orch.process_turn(conv, "Asa")            # name -> phone
    orch.process_turn(conv, "070-999 88 77")  # phone -> matches existing hash
    conv.refresh_from_db()
    assert conv.case_state["returning"] is True
    orch.process_turn(conv, "skip")           # email skip -> postal
    orch.process_turn(conv, "skip")           # postal skip -> address
    orch.process_turn(conv, "skip")           # address skip -> approval
    done = orch.process_turn(conv, "yes_send")
    assert "welcome back" in done["message"].lower() or "välkommen" in done["message"].lower()


def test_f4_returning_customer_links_to_existing_not_duplicated(seeded, mock_gemini):
    """F4: _sync_customer matches the pre-existing Customer by phone_hash, so a
    returning caller's lead lands on their original profile, never a duplicate."""
    from crm.models import phone_hash

    existing = Customer.objects.create(
        name="Asa Prior", phone="+46709998877", phone_hash=phone_hash("+46709998877"),
        consent_to_contact=True)
    conv, _ = orch.open_conversation()
    _to_unsupported_escalation(conv, mock_gemini)
    orch.process_turn(conv, "skip")
    orch.process_turn(conv, "Asa")
    orch.process_turn(conv, "070-999 88 77")
    orch.process_turn(conv, "skip")              # email -> postal
    orch.process_turn(conv, "skip")              # postal -> address
    orch.process_turn(conv, "skip")              # address -> approval
    orch.process_turn(conv, "yes_send")

    sess = Session.objects.get(conversation=conv)
    assert sess.customer_id == existing.pk       # linked, not duplicated
    assert Customer.objects.filter(phone="+46709998877").count() == 1
