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
    orch.process_turn(conv, "no_heat")
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")            # → escalate, asks name
    assert res["decision"] == "escalate"
    orch.process_turn(conv, "Jane Tester")              # name → phone
    orch.process_turn(conv, "070-1234567")              # phone → email
    orch.process_turn(conv, "skip")                     # email skipped → postal
    approval = orch.process_turn(conv, "98101 Kiruna")  # postal → approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    done = orch.process_turn(conv, "yes_send")          # → dispatch
    assert "Nordland" in done["message"]

    sess = Session.objects.get(conversation=conv)
    assert sess.customer.name == "Jane Tester"
    assert sess.customer.phone == "070-1234567"
    assert sess.customer.consent_to_contact is True
    assert sess.booking_requested is True
    assert sess.status == "escalated"
    sr = ServiceRequest.objects.get(session=sess)
    assert LeadDelivery.objects.get(service_request=sr, sink="db").status == "success"
