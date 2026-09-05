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


# ── UX/a11y regressions (perceived speed, empty states, "works no matter what") ──

def test_htmx_feedback_wiring_present_on_every_page(staff, client):
    """base.html wires one global handler so every htmx action (current or future)
    gets a busy affordance, a double-submit guard, and a visible failure — instead
    of each template remembering to add hx-indicator/hx-disabled-elt by hand."""
    html = client.get("/dashboard/").content.decode()
    assert "htmx:beforeRequest" in html
    assert "htmx:responseError" in html
    assert "nl-busy" in html


def test_alpine_cloak_used_so_nothing_flashes_before_hydration(staff, client):
    html = client.get("/dashboard/").content.decode()
    assert "x-cloak" in html


def test_sidebar_has_no_js_fallback(staff, client):
    """Without JS the off-canvas drawer can never be opened — so the fallback
    must render the sidebar in normal flow on mobile and hide the dead toggle."""
    html = client.get("/dashboard/").content.decode()
    assert "<noscript>" in html
    assert 'id="sidebar-toggle"' in html
    assert "#sidebar-toggle { display: none; }" in html


def test_sidebar_toggle_has_aria_wiring(staff, client):
    html = client.get("/dashboard/").content.decode()
    assert 'aria-controls="app-sidebar"' in html
    assert ":aria-expanded=" in html


def test_session_list_empty_state_vs_populated(staff, client, a_session):
    empty_html = client.get("/dashboard/sessions/?q=NO_SUCH_MATCH_XYZ").content.decode()
    assert "No matching conversations" in empty_html
    populated_html = client.get("/dashboard/sessions/").content.decode()
    assert "No matching conversations" not in populated_html
    assert "No conversations yet" not in populated_html


def test_customer_list_uses_empty_state_when_empty(staff, client):
    html = client.get("/dashboard/customers/").content.decode()
    assert "No customers yet" in html
    # shared empty-state partial, not a bare empty table
    assert 'class="flex flex-col items-center justify-center text-center' in html
