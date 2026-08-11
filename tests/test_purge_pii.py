"""crm.purge_pii — GDPR retention/erasure (V2 P-F)."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from django.core.files.uploadedfile import SimpleUploadedFile

from chat.models import Conversation
from crm.models import Customer, CustomerFile, ServiceRequest, Session, UnrevokedExternalCopy

pytestmark = pytest.mark.django_db


def _old_customer(**kwargs):
    cust = Customer.objects.create(**kwargs)
    Customer.objects.filter(pk=cust.pk).update(created_at=timezone.now() - timedelta(days=400))
    cust.refresh_from_db()
    return cust


def test_purge_scrubs_pii_from_service_request_surviving_a_deleted_customer():
    """Session.customer is SET_NULL — a Session whose Conversation is recent survives
    custs.delete(), but its ServiceRequest.payload_json is a point-in-time snapshot
    that would otherwise keep the customer's name/phone/email/address forever."""
    cust = _old_customer(name="Anna", phone="0701234567", email="a@x.se", address="Storgatan 1")
    conv = Conversation.objects.create()  # recent — not purged
    sess = Session.objects.create(conversation=conv, customer=cust)
    sr = ServiceRequest.objects.create(
        session=sess, idempotency_key="k1",
        payload_json={"customer": {"name": "Anna", "phone": "0701234567",
                                    "email": "a@x.se", "address": "Storgatan 1"}},
    )

    call_command("purge_pii", days=365, yes=True)

    assert not Customer.objects.filter(pk=cust.pk).exists()
    sr.refresh_from_db()
    dump = str(sr.payload_json)
    assert "Anna" not in dump
    assert "0701234567" not in dump
    assert "a@x.se" not in dump
    assert "Storgatan 1" not in dump


def test_purge_dry_run_does_not_scrub_or_delete():
    cust = _old_customer(name="Anna")
    conv = Conversation.objects.create()
    sess = Session.objects.create(conversation=conv, customer=cust)
    sr = ServiceRequest.objects.create(
        session=sess, idempotency_key="k2", payload_json={"customer": {"name": "Anna"}})

    call_command("purge_pii", days=365)  # no --yes

    assert Customer.objects.filter(pk=cust.pk).exists()
    sr.refresh_from_db()
    assert sr.payload_json["customer"]["name"] == "Anna"


def test_purge_cascades_service_request_when_conversation_also_old():
    cust = _old_customer(name="Bo")
    conv = Conversation.objects.create()
    Conversation.objects.filter(pk=conv.pk).update(started_at=timezone.now() - timedelta(days=400))
    sess = Session.objects.create(conversation=conv, customer=cust)
    ServiceRequest.objects.create(
        session=sess, idempotency_key="k3", payload_json={"customer": {"name": "Bo"}})

    call_command("purge_pii", days=365, yes=True)

    assert not Customer.objects.filter(pk=cust.pk).exists()
    assert not Conversation.objects.filter(pk=conv.pk).exists()
    assert not ServiceRequest.objects.filter(idempotency_key="k3").exists()


def test_purge_records_unrevoked_drive_mirror_and_says_so(settings, tmp_path, capsys):
    """A customer photo mirrored to Google Drive (drive_url set) must not be reported
    as gone — purge_pii has no way to revoke the external copy, so it must record the
    URL persistently and say so plainly in its summary."""
    settings.MEDIA_ROOT = str(tmp_path)
    cust = _old_customer(name="Eva")
    cf = CustomerFile.objects.create(
        customer=cust, file=SimpleUploadedFile("nameplate.jpg", b"bytes"), kind="photo",
        drive_url="https://drive.google.com/file/d/abc123/view")

    call_command("purge_pii", days=365, yes=True)

    assert not Customer.objects.filter(pk=cust.pk).exists()
    assert not CustomerFile.objects.filter(pk=cf.pk).exists()

    remaining = UnrevokedExternalCopy.objects.filter(drive_url=cf.drive_url)
    assert remaining.exists()
    assert remaining.first().file_kind == "photo"

    out = capsys.readouterr().out
    assert "external" in out.lower()
    assert "1" in out


def test_purge_dry_run_reports_unrevoked_count_without_recording(settings, tmp_path, capsys):
    settings.MEDIA_ROOT = str(tmp_path)
    cust = _old_customer(name="Nils")
    CustomerFile.objects.create(
        customer=cust, file=SimpleUploadedFile("receipt.jpg", b"bytes"), kind="photo",
        drive_url="https://drive.google.com/file/d/xyz/view")

    call_command("purge_pii", days=365)  # no --yes

    assert Customer.objects.filter(pk=cust.pk).exists()
    assert UnrevokedExternalCopy.objects.count() == 0
    out = capsys.readouterr().out
    assert "external" in out.lower()
