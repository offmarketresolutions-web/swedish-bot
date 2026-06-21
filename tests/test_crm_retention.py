"""V2 P-E — CRM retention: file retention, summary-on-idle, customer profile + media."""
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from chat.models import Conversation, Message
from crm import leads
from crm.models import Customer, CustomerFile, Session

pytestmark = pytest.mark.django_db


def _session_with_photo():
    conv = Conversation.objects.create()
    Message.objects.create(conversation=conv, role="user", content="my pump leaks")
    Message.objects.create(conversation=conv, role="user",
                           image=SimpleUploadedFile("p.jpg", b"\xff\xd8\xffphoto-bytes", "image/jpeg"))
    cust = Customer.objects.create(name="Jan", phone="070", consent_to_contact=True)
    return Session.objects.create(conversation=conv, customer=cust, manufacturer="IVT", model="Geo 600C")


def test_attach_customer_files_idempotent(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    sess = _session_with_photo()
    assert leads.attach_customer_files(sess) == 1
    assert leads.attach_customer_files(sess) == 0          # same content → no dup
    assert CustomerFile.objects.filter(customer=sess.customer).count() == 1


def test_summarize_idle_fills_missing_summary(mock_gemini):
    sess = _session_with_photo()
    Session.objects.filter(pk=sess.pk).update(ai_summary="", updated_at=timezone.now() - timedelta(hours=1))
    call_command("summarize_idle", "--idle-minutes", "30")
    sess.refresh_from_db()
    assert sess.ai_summary  # summarizer ran (mocked → non-empty)


@pytest.fixture
def staff(client):
    client.force_login(User.objects.create_user("ops", password="x", is_staff=True))


def test_customer_pages_and_media(staff, client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    sess = _session_with_photo()
    leads.attach_customer_files(sess)
    cf = CustomerFile.objects.get(customer=sess.customer)

    r = client.get("/dashboard/customers/")
    assert r.status_code == 200 and b"Jan" in r.content
    r = client.get(f"/dashboard/customers/{sess.customer.pk}/")
    assert r.status_code == 200 and b"Geo 600C" in r.content

    r = client.get(f"/dashboard/files/{cf.pk}/")
    assert r.status_code == 200
    assert "attachment" in r["Content-Disposition"]
    assert r["X-Content-Type-Options"] == "nosniff"


def test_media_requires_staff(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    sess = _session_with_photo()
    leads.attach_customer_files(sess)
    cf = CustomerFile.objects.get(customer=sess.customer)
    r = client.get(f"/dashboard/files/{cf.pk}/")
    assert r.status_code == 302  # gated → redirect to admin login
