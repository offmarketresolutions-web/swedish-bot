"""Dashboard: auth gate, render, and editable reporting fields (plan §9)."""
import pytest
from django.contrib.auth.models import User

from chat.models import Conversation, Message
from crm.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def a_session():
    conv = Conversation.objects.create()
    Message.objects.create(conversation=conv, role="user", content="my IVT 490 is beeping")
    Message.objects.create(conversation=conv, role="assistant", content="Note the alarm code.")
    return Session.objects.create(conversation=conv, manufacturer="IVT", model="IVT 490",
                                  severity="normal", decision="escalate", status="escalated")


def test_dashboard_requires_auth(client):
    resp = client.get("/dashboard/")
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"] or "login" in resp.headers["Location"]


def test_overview_renders(staff, client, a_session):
    resp = client.get("/dashboard/")
    assert resp.status_code == 200
    assert b"Overview" in resp.content


def test_session_list_and_filter(staff, client, a_session):
    resp = client.get("/dashboard/sessions/?severity=normal")
    assert resp.status_code == 200
    assert b"IVT 490" in resp.content


def test_session_detail_renders_transcript(staff, client, a_session):
    resp = client.get(f"/dashboard/sessions/{a_session.pk}/")
    assert resp.status_code == 200
    assert b"my IVT 490 is beeping" in resp.content
    assert b"Note the alarm code." in resp.content


def test_session_detail_edit_updates_fields(staff, client, a_session):
    resp = client.post(f"/dashboard/sessions/{a_session.pk}/", data={
        "severity": "urgent", "resolved": "on", "ai_summary": "edited summary",
    })
    assert resp.status_code == 302
    a_session.refresh_from_db()
    assert a_session.severity == "urgent"
    assert a_session.resolved is True
    assert a_session.service_recommended is False  # unchecked → False
    assert a_session.ai_summary == "edited summary"
