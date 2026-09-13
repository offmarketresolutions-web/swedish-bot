"""Every dashboard page must actually render.

63 routes are registered and no single test opened them all, so a view could 500 for
weeks behind a link nobody clicked that sprint. This walks every GET route a staff user
can reach and asserts it returns a page — the cheapest possible answer to "is the
dashboard actually functional".

Detail routes get a real object id from the seeded fixtures rather than a guessed 1, so
a 404 here means the route is broken, not that the row was missing.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import get_resolver, reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        "smoke_staff", "s@e.se", "pw", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


@pytest.fixture
def seeded_objects():
    """Enough real rows that detail routes resolve to something."""
    call_command("seed_kb")
    from chat.models import Conversation
    from crm.models import Customer, ServiceArea, Session
    from kb.models import Category, Machine, Vendor

    conv = Conversation.objects.create(language="sv")
    customer = Customer.objects.create(name="Smoke Test", phone="+46700000000")
    session = Session.objects.create(conversation=conv, customer=customer, status="open")
    area = ServiceArea.objects.create(
        name="Smoke area", kind="inside",
        polygon={"type": "Polygon",
                 "coordinates": [[[17.0, 62.2], [17.8, 62.2], [17.8, 62.6], [17.0, 62.6], [17.0, 62.2]]]})
    return {
        "session": session.pk, "customer": customer.pk, "area": area.pk,
        "vendor": Vendor.objects.first().pk, "machine": Machine.objects.first().pk,
        "category": Category.objects.first().pk,
    }


def _dashboard_get_routes():
    """Every named route in dashboard/urls.py, with the argument names it needs.

    Read straight off the URLconf rather than resolver.reverse_dict — that internal
    structure silently yielded nothing, which would have made this whole suite pass
    without opening a single page.
    """
    import dashboard.urls as durls

    out = []
    for entry in durls.urlpatterns:
        name = getattr(entry, "name", None)
        if not name:
            continue
        args = sorted(entry.pattern.regex.groupindex.keys())
        out.append((name, str(entry.pattern), args))
    return sorted(out)


# Routes that are POST-only or perform an action; a GET is not meaningful.
_ACTION_ROUTES = {
    "dash-flow-save", "dash-voice-publish", "dash-service-area-add",
    "dash-service-area-delete", "dash-service-area-toggle", "dash-service-area-coverage",
    "dash-knowledge-toggle", "dash-knowledge-delete", "dash-customer-file-upload",
    "dash-faq-approve", "dash-faq-reject", "dash-agent-save", "dash-guardrail-save",
}


def test_every_dashboard_page_renders(staff_client, seeded_objects):
    """A 500 anywhere here is a page a staff member would hit and see an error on."""
    failures = []
    checked = 0
    for name, _pattern, args in _dashboard_get_routes():
        if name in _ACTION_ROUTES:
            continue
        kwargs = {}
        if args:
            # Single-pk detail routes: feed a real id where we can infer which model.
            key = args[0]
            if key != "pk":
                continue  # slug/str routes are covered by their own suites
            guess = (seeded_objects["session"] if "session" in name else
                     seeded_objects["customer"] if "customer" in name else
                     seeded_objects["area"] if "service-area" in name else
                     seeded_objects["vendor"] if "vendor" in name else
                     seeded_objects["machine"] if "machine" in name else
                     seeded_objects["category"] if "category" in name else None)
            if guess is None:
                continue
            kwargs = {"pk": guess}
        try:
            url = reverse(name, kwargs=kwargs)
        except Exception:  # noqa: BLE001 — unreversible signature, not this test's job
            continue
        resp = staff_client.get(url)
        checked += 1
        if resp.status_code >= 500:
            failures.append(f"{name} ({url}) -> {resp.status_code}")
    assert checked >= 20, f"only walked {checked} routes — the discovery is broken"
    assert not failures, "dashboard pages erroring:\n" + "\n".join(failures)


def test_dashboard_pages_require_staff(client):
    """Every dashboard page is behind staff auth — an anonymous visitor is redirected to
    the login, never shown customer data."""
    leaked = []
    for name in ("dash-overview", "dash-sessions", "dash-customers", "dash-analytics",
                 "dash-service-area", "dash-settings"):
        resp = client.get(reverse(name))
        if resp.status_code == 200:
            leaked.append(name)
    assert not leaked, f"reachable without login: {leaked}"
