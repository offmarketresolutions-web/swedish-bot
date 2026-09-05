"""Sidebar reachability: every link in the dashboard nav resolves and renders 200,
and the Settings area exposes both tabs (integrations + API credentials)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ops", password="x", is_staff=True)
    client.force_login(user)
    return user


# Every named route the sidebar links to (base.html), in nav order.
SIDEBAR_ROUTES = [
    "dash-overview", "dash-analytics",
    "dash-sessions", "dash-customers",
    "dash-kb", "dash-faq", "dash-agents", "dash-guardrails", "dash-flow",
    "dash-voice-phone",
    "homepage-demo",
    "dash-settings", "dash-voice-credentials",
]


@pytest.mark.parametrize("name", SIDEBAR_ROUTES)
def test_sidebar_link_renders(staff, client, name):
    resp = client.get(reverse(name))
    assert resp.status_code == 200, f"{name} -> {resp.status_code}"


def test_settings_pages_cross_link_via_tabs(staff, client):
    for name in ("dash-settings", "dash-voice-credentials"):
        html = client.get(reverse(name)).content.decode()
        assert 'data-testid="settings-tabs"' in html
        assert reverse("dash-settings") in html
        assert reverse("dash-voice-credentials") in html


def test_sidebar_contains_all_groups_and_demo_links(staff, client):
    html = client.get(reverse("dash-overview")).content.decode()
    for route in SIDEBAR_ROUTES:
        assert reverse(route) in html, f"sidebar missing link to {route}"
    assert 'data-testid="nav-homepage-demo"' in html
    assert 'data-testid="nav-test-chat"' in html


def test_settings_tabs_mark_only_active_tab_aria_current():
    """Render the tab strip in isolation (the full page also sets aria-current
    on the matching sidebar entry, which would double-count here)."""
    from django.template.loader import render_to_string

    html = render_to_string("dashboard/_settings_tabs.html", {"url": "dash-voice-credentials"})
    assert html.count('aria-current="page"') == 1
    tabs = [chunk for chunk in html.split("<a ") if chunk.strip()]
    current_tabs = [t for t in tabs if 'aria-current="page"' in t]
    assert len(current_tabs) == 1
    assert "API credentials" in current_tabs[0]


def test_sidebar_nav_links_are_plain_hrefs(staff, client):
    """No destructive/critical nav depends on JS: every sidebar entry is a real
    <a href> that resolves, independent of htmx/Alpine (checked statically here;
    test_sidebar_link_renders above proves each target itself renders 200)."""
    html = client.get(reverse("dash-overview")).content.decode()
    for route in SIDEBAR_ROUTES:
        assert f'href="{reverse(route)}"' in html
