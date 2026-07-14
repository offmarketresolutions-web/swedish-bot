"""Lead sinks + escalation→lead flow (plan §6/§9)."""
import pytest
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

from chat import orchestrator as orch
from crm import leads, sinks
from crm.models import Customer, LeadDelivery, ServiceRequest, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


def _session_with_customer():
    from chat.models import Conversation
    conv = Conversation.objects.create()
    cust = Customer.objects.create(name="Jane", phone="555", email="j@x.se", postal_code="98901",
                                   consent_to_contact=True)
    return Session.objects.create(conversation=conv, customer=cust, manufacturer="IVT",
                                  model="IVT 490", severity="normal", ai_summary="summary")


def test_db_sink_always_succeeds_email_skipped_by_default(seeded, mock_gemini):
    sess = _session_with_customer()
    sr, results = leads.create_and_dispatch(sess, "low_confidence")
    assert results["db"] == "success"
    assert results["email"] == "skipped"        # no LEAD_EMAIL_TO configured
    assert results["webhook"] == "skipped"
    assert results["wordpress"] == "skipped"
    assert ServiceRequest.objects.count() == 1


def test_payload_includes_previous_installer_when_known(seeded, mock_gemini):
    sess = _session_with_customer()
    sess.installer = "bylunds"
    sess.save(update_fields=["installer"])
    sr, _ = leads.create_and_dispatch(sess, "low_confidence")
    assert sr.payload_json["installer"] == "bylunds"


def test_payload_installer_blank_when_unknown(seeded, mock_gemini):
    sess = _session_with_customer()
    sr, _ = leads.create_and_dispatch(sess, "low_confidence")
    assert sr.payload_json["installer"] == ""


@override_settings(LEAD_EMAIL_TO="ops@nordlandvvs.se",
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_sink_sends_when_configured(seeded, mock_gemini):
    sess = _session_with_customer()
    leads.create_and_dispatch(sess, "low_confidence")
    assert len(mail.outbox) == 1
    assert "IVT 490" in mail.outbox[0].subject
    assert "Jane" in mail.outbox[0].body


def test_one_failing_sink_does_not_block_others(seeded, mock_gemini, monkeypatch):
    sess = _session_with_customer()

    def boom(self, sr):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sinks.DBSink, "deliver", boom)  # force db sink to fail
    sr, results = leads.create_and_dispatch(sess, "x")
    assert results["db"] == "failed"
    d = LeadDelivery.objects.get(service_request=sr, sink="db")
    assert "kaboom" in d.last_error
    # other sinks still evaluated (skipped, not blocked)
    assert results["email"] == "skipped"


def test_dispatch_is_idempotent(seeded, mock_gemini):
    sess = _session_with_customer()
    sr1, _ = leads.create_and_dispatch(sess, "reason-a")
    sr2, r2 = leads.create_and_dispatch(sess, "reason-a")
    assert sr1.pk == sr2.pk                      # same idempotency key → same request
    assert ServiceRequest.objects.count() == 1
    assert LeadDelivery.objects.filter(service_request=sr1, sink="db").count() == 1
    assert r2["db"] == "success"


def test_escalation_collects_contact_and_creates_lead(seeded, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "I'm not certain enough to advise safely.",
        "confidence": 0.4, "decision": "solve", "in_docs": True, "report": {},
    }
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")                       # postcode asked early (declined → unknown)
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")            # → escalate; asks problem detail + error-code photo
    assert res["decision"] == "escalate"
    orch.process_turn(conv, "It rattles loudly and shows code E9")  # diagnostics reply → asks name
    orch.process_turn(conv, "Jane Tester")              # name → phone
    orch.process_turn(conv, "070-1234567")              # phone → email
    orch.process_turn(conv, "skip")                     # email skipped → postal
    orch.process_turn(conv, "98101 Kiruna")             # postal → address
    approval = orch.process_turn(conv, "Storgatan 5")   # address → approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    assert "Storgatan 5" in approval["message"]         # address echoed in the approval summary
    done = orch.process_turn(conv, "yes_send")          # → dispatch
    assert "Nordland" in done["message"]

    sess = Session.objects.get(conversation=conv)
    assert sess.customer.name == "Jane Tester"
    assert sess.customer.address == "Storgatan 5"       # installation address persisted
    sr0 = ServiceRequest.objects.get(session=sess)
    assert sr0.payload_json["customer"]["address"] == "Storgatan 5"  # rides the lead payload
    assert sess.customer.phone == "+46701234567"   # normalized to E.164 at capture
    assert sess.customer.consent_to_contact is True
    assert sess.booking_requested is True
    assert sess.status == "escalated"
    sr = ServiceRequest.objects.get(session=sess)
    assert LeadDelivery.objects.get(service_request=sr, sink="db").status == "success"


def test_declining_all_contact_does_not_record_junk_or_dispatch(seeded, mock_gemini):
    """A customer who answers 'no' to every contact question must NOT have 'no' stored
    as their name/phone, and we must not dispatch an unreachable lead — close gracefully."""
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "not sure", "confidence": 0.3, "decision": "escalate",
        "in_docs": False, "report": {},
    }
    conv, _ = orch.open_conversation()
    for t in ["heat_pump", "no", "no_heat", "IVT", "IVT 490"]:  # "no" = postcode declined early
        orch.process_turn(conv, t)
    orch.process_turn(conv, "no")          # diagnostics → name
    orch.process_turn(conv, "no")          # name declined → phone
    orch.process_turn(conv, "no")          # phone declined → email
    orch.process_turn(conv, "no")          # email declined → postal
    orch.process_turn(conv, "no")          # postal declined → address
    orch.process_turn(conv, "no")          # address declined → "need a phone" gate
    final = orch.process_turn(conv, "no")  # still declines → graceful close
    assert "website" in final["message"].lower()
    # graceful close: no unreachable lead dispatched, and no junk customer recorded
    assert ServiceRequest.objects.count() == 0
    assert not Customer.objects.filter(name="no").exists()
    assert not Customer.objects.filter(phone__in=("no", "")).exists()


@pytest.mark.django_db
def test_long_guardrail_reason_is_clamped(mock_gemini):
    """An unbounded LLM guardrail reason must not overflow escalation_reason varchar(120).

    Regression: live eval R013 crashed lead dispatch with StringDataRightTruncation."""
    sess = _session_with_customer()
    long_reason = "customer asked about opening the sealed refrigerant circuit " * 10
    sr, _results = leads.create_and_dispatch(sess, reason=long_reason)
    assert len(sr.escalation_reason) <= 120
    assert sr.escalation_reason == long_reason[:120]
