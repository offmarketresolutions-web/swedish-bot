"""V2 P-F — returning-customer recognition (phone-hash, minimal disclosure) + GDPR."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from chat import orchestrator as orch
from chat.models import Conversation
from crm.models import Customer, phone_hash

pytestmark = pytest.mark.django_db


def test_phone_hash_is_stable_and_normalized(settings):
    settings.PHONE_HASH_PEPPER = "pep"
    assert phone_hash("070-12 34 567") == phone_hash("0701234567")  # punctuation/spaces ignored
    assert phone_hash("") == ""
    assert phone_hash("070") != ""


def test_phone_hash_set_on_save():
    c = Customer.objects.create(name="A", phone="070-1234567")
    assert c.phone_hash and c.phone_hash == phone_hash("070-1234567")


def _to_escalation(conv, mock_gemini):
    mock_gemini.responses["specialist"] = {
        "answer_to_customer": "Uncertain.", "confidence": 0.4, "decision": "solve",
        "in_docs": True, "report": {}}
    for m in ("heat_pump", "no", "no_heat", "IVT", "IVT 490"):  # "no" = postcode declined early
        orch.process_turn(conv, m)
    orch.process_turn(conv, "rattles, code E9")  # diagnostics reply → asks name


@pytest.fixture
def seeded():
    call_command("seed_kb")


def test_returning_customer_recognized_minimal_disclosure(seeded, mock_gemini):
    Customer.objects.create(name="Prior", phone="070-1234567",
                            consent_to_contact=True)  # prior contact on file
    conv, _ = orch.open_conversation()
    _to_escalation(conv, mock_gemini)
    orch.process_turn(conv, "Jan")
    orch.process_turn(conv, "070-1234567")        # same phone → recognized
    orch.process_turn(conv, "skip")
    orch.process_turn(conv, "98101")
    done = orch.process_turn(conv, "yes_send")
    assert "Welcome back" in done["message"]       # minimal acknowledgement
    assert "IVT 490" not in done["message"]        # no prior-machine details leaked


def test_new_customer_not_recognized(seeded, mock_gemini):
    conv, _ = orch.open_conversation()
    _to_escalation(conv, mock_gemini)
    for m in ("Jan", "070-9999999", "skip", "98101"):
        orch.process_turn(conv, m)
    done = orch.process_turn(conv, "yes_send")
    assert "Welcome back" not in done["message"]


def test_purge_pii_dry_run_then_delete():
    c = Customer.objects.create(name="Old", phone="070-1")
    conv = Conversation.objects.create()
    old = timezone.now() - timedelta(days=400)
    Customer.objects.filter(pk=c.pk).update(created_at=old)
    Conversation.objects.filter(pk=conv.pk).update(started_at=old)

    call_command("purge_pii", "--days", "365")     # dry run → nothing deleted
    assert Customer.objects.filter(pk=c.pk).exists()

    call_command("purge_pii", "--days", "365", "--yes")
    assert not Customer.objects.filter(pk=c.pk).exists()
    assert not Conversation.objects.filter(pk=conv.pk).exists()
