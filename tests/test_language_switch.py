"""The operator must be able to switch the dashboard language and have it stick.

Before this existed the plumbing was half-built: LocaleMiddleware and LANGUAGES were
configured, but config/urls.py never included django.conf.urls.i18n, so there was no
set_language endpoint — nothing could change the active language — and locale/sv had a
.po with no compiled .mo, so even a correct language choice would render English.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    user = get_user_model().objects.create_user(
        username="op", password="pw", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def test_set_language_endpoint_exists():
    assert reverse("set_language") == "/i18n/setlang/"


def test_dashboard_renders_a_language_switcher(staff_client):
    body = staff_client.get(reverse("dash-overview")).content.decode("utf-8")
    assert 'action="/i18n/setlang/"' in body, "no language switcher form on the dashboard"
    assert 'name="language"' in body
    # Must work without JS: a real POST form with a submit path, not an onclick-only control.
    assert 'method="post"' in body
    assert "csrfmiddlewaretoken" in body, "switcher POST would 403 without a CSRF token"
    for code in ("en", "sv"):
        assert f'value="{code}"' in body, f"{code} missing from the switcher"


def test_switching_language_persists_across_requests(staff_client):
    resp = staff_client.post(reverse("set_language"),
                             {"language": "sv", "next": reverse("dash-overview")})
    assert resp.status_code in (302, 200)
    # Django 4+ set_language persists via a cookie (LANGUAGE_SESSION_KEY was removed),
    # which LocaleMiddleware reads on every later request.
    from django.conf import settings
    cookie = staff_client.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    assert cookie is not None and cookie.value == "sv", (
        f"language cookie not set — got {cookie.value if cookie else None!r}"
    )


def test_swedish_actually_renders_translated_text(staff_client):
    """The switcher is hollow without compiled translations: locale/sv/LC_MESSAGES had a
    stale .po (33 msgids against ~586 {% trans %} tags) and NO .mo at all, so Django fell
    back to the English source for every string. `make messages` compiles it."""
    staff_client.post(reverse("set_language"),
                      {"language": "sv", "next": reverse("dash-overview")})
    body = staff_client.get(reverse("dash-overview")).content.decode("utf-8")
    assert 'lang="sv"' in body, "page did not switch to the sv locale"
    from django.utils import translation
    with translation.override("sv"):
        assert str(translation.gettext("Conversations")) != "Conversations", (
            "no Swedish translation is active — locale/sv/LC_MESSAGES/django.mo is missing "
            "or empty; run `make messages`"
        )
