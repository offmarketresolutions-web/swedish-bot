"""E2E: a full escalation with rich facts must produce a Customer profile that
"logs everything" — contact incl. address, machine/brand/category linkage, a
concise problem descriptor, and a renderable dashboard profile page showing all
of it (docs/plans owner ask: "creating customers and storing all the details +
machine + contact + conversation summary ... describe their problem concise").
"""
import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from chat import orchestrator as orch
from crm.models import Customer, Session
from tests.support.convo import finish_escalation

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded():
    call_command("seed_kb")


@pytest.fixture
def staff(client):
    u = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(u)
    return u


def _rich_escalation(mock_gemini):
    """Drive category → postcode(decline) → problem-category chip (so
    Session.problem_category/category gets resolved, unlike free-text problem
    mining) → error code + onset (mined via bulk on the model turn) → brand →
    confirmed model → escalate, then finish contact with name/phone/email/postal/
    address, mirroring tests/test_leads.py's test_escalation_collects_contact_and_creates_lead
    + tests/test_contact_address.py."""
    mock_gemini.responses["bulk"] = {
        "category": None, "subtype": None, "brand": None, "model": None,
        "error_code": "H01 5252", "alarm_text": None, "onset": "sudden", "postal_code": None,
        "installer": None, "operating_context": None, "readings": [], "problem": None,
    }
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Since it's returned after cleaning, this needs a technician.",
        "confidence": 0.5, "decision": "escalate", "in_docs": True, "report": {},
    }
    # router resolves the problem_category slug -> Session.problem_category/category FK
    mock_gemini.responses["router"] = {"severity": "normal", "supported": True, "problem_category": "no_heat"}
    conv, _ = orch.open_conversation()
    orch.process_turn(conv, "heat_pump")
    orch.process_turn(conv, "no")  # postcode asked early — declined (captured later at contact)
    orch.process_turn(conv, "no_heat")  # problem-category chip -> resolves Session.problem_category/category
    orch.process_turn(conv, "IVT")
    res = orch.process_turn(conv, "IVT 490")  # error code + onset mined here; confirmed model
    assert res["decision"] == "escalate"
    return conv


def test_full_escalation_populates_customer_profile(seeded, mock_gemini):
    conv = _rich_escalation(mock_gemini)
    finish_escalation(
        conv, diag_reply="It keeps rattling and the alarm returns",
        name="Anna Karlsson", phone="070-987 65 43", email="anna@example.se",
        postal="98101 Kiruna", address="Storgatan 5", approve=True,
    )

    sess = Session.objects.get(conversation=conv)
    cust = sess.customer
    assert cust is not None

    # ── contact ──────────────────────────────────────────────────────
    assert cust.name == "Anna Karlsson"
    assert cust.phone == "+46709876543"          # E.164 normalized
    assert cust.email == "anna@example.se"
    assert cust.address == "Storgatan 5"
    assert cust.postal_code.strip() == "98101"
    assert cust.consent_to_contact is True

    # ── machine / brand / category linkage ──────────────────────────
    assert cust.primary_machine is not None
    assert cust.primary_machine.model_name == "IVT 490"
    assert cust.primary_brand is not None
    assert cust.primary_brand.name == "IVT"
    assert cust.primary_category is not None
    assert "IVT 490" in cust.equipment_summary

    # ── conversation summary ─────────────────────────────────────────
    assert sess.ai_summary  # populated by leads.create_and_dispatch (build_summary)

    # ── concise problem descriptor (deterministic, not an LLM call) ─
    assert cust.profile_summary
    assert "IVT 490" in cust.profile_summary
    assert "H01 5252" in cust.profile_summary
    assert len(cust.profile_summary) <= 200


def test_profile_page_renders_contact_machine_summary_and_problem(seeded, mock_gemini, staff, client):
    conv = _rich_escalation(mock_gemini)
    finish_escalation(
        conv, diag_reply="It keeps rattling and the alarm returns",
        name="Anna Karlsson", phone="070-987 65 43", email="anna@example.se",
        postal="98101 Kiruna", address="Storgatan 5", approve=True,
    )
    sess = Session.objects.get(conversation=conv)
    cust = sess.customer

    resp = client.get(f"/dashboard/customers/{cust.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    # contact block incl. address
    assert "Storgatan 5" in html
    assert "98101" in html
    assert "anna@example.se" in html

    # machine info
    assert "IVT 490" in html
    assert "IVT" in html

    # concise problem, prominent
    assert cust.profile_summary in html
    assert 'data-testid="customer-problem-summary"' in html

    # conversation summary (ai_summary) surfaced per session
    assert 'data-testid="customer-conversations"' in html


def test_returning_customer_updates_not_duplicates_profile(seeded, mock_gemini):
    """A second escalation from the same phone must update the existing Customer
    row (address/profile_summary refreshed to the newer case), never create a
    duplicate — and PII purge/consent semantics stay intact."""
    conv1 = _rich_escalation(mock_gemini)
    finish_escalation(
        conv1, diag_reply="rattling", name="Anna Karlsson", phone="070-987 65 43",
        email="anna@example.se", postal="98101 Kiruna", address="Storgatan 5", approve=True,
    )
    assert Customer.objects.filter(phone="+46709876543").count() == 1
    cust_id = Customer.objects.get(phone="+46709876543").pk

    mock_gemini.responses["bulk"] = {
        "category": None, "subtype": None, "brand": None, "model": None,
        "error_code": "F2", "alarm_text": None, "onset": "gradual", "postal_code": None,
        "installer": None, "operating_context": None, "readings": [], "problem": "läcker vatten",
    }
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "This needs a technician.", "confidence": 0.5,
        "decision": "escalate", "in_docs": True, "report": {},
    }
    conv2, _ = orch.open_conversation()
    orch.process_turn(conv2, "heat_pump")
    orch.process_turn(conv2, "no")
    orch.process_turn(conv2, "Visar F2, läcker vatten")
    orch.process_turn(conv2, "IVT")
    orch.process_turn(conv2, "IVT 490")
    # A known address is NOT re-asked for a returning customer (chat/orchestrator.py
    # _sync_customer/_escalate_step address-skip; see tests/test_contact_address.py::
    # test_returning_customer_skips_known_address) — drive the shortened sequence
    # directly instead of tests.support.convo.finish_escalation, which assumes address
    # is always asked and would misalign on the extra turn.
    orch.process_turn(conv2, "leaking more now")  # diag reply -> name
    orch.process_turn(conv2, "Anna Karlsson")      # name -> phone
    orch.process_turn(conv2, "070-987 65 43")       # phone -> email
    orch.process_turn(conv2, "anna@example.se")     # email -> postal
    approval = orch.process_turn(conv2, "98101 Kiruna")  # postal -> (address known, skipped) -> approval
    assert {c["value"] for c in approval["chips"]} == {"yes_send", "not_yet"}
    orch.process_turn(conv2, "yes_send")

    assert Customer.objects.filter(phone="+46709876543").count() == 1  # no duplicate
    cust = Customer.objects.get(pk=cust_id)
    # a known address is not re-asked (see test_contact_address.test_returning_customer_skips_known_address)
    # so it stays what the first escalation recorded — the profile is updated, not duplicated
    assert cust.address == "Storgatan 5"
    assert "F2" in cust.profile_summary  # refreshed to the newer case
    assert cust.sessions.count() == 2
