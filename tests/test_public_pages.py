"""Statically-checkable accessibility/perf/robustness assertions for the two
public-facing demo pages (homepage_demo.html, demo_form.html) and the prefill
snippet. Complements the render/embed checks in test_widget.py."""
import re

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

ALLOWED_STYLESHEET_HOSTS = ("fonts.googleapis.com",)
ALLOWED_SCRIPT_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "cdn.tailwindcss.com", "code.jquery.com")


def _get(path):
    return Client().get(path).content.decode()


def _form_html():
    return _get("/demo/form")


def _homepage_html():
    return _get("/demo/homepage")


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def test_demo_form_every_control_has_a_bound_label():
    html = _form_html()
    control_ids = set(re.findall(r'<(?:input|select|textarea)[^>]*\bid="([^"]+)"', html))
    label_fors = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', html))
    # every id'd control (except the hidden readonly service_area, which is fine either way)
    assert control_ids, "expected labelled form controls in demo_form.html"
    assert control_ids <= label_fors, f"controls without a bound label: {control_ids - label_fors}"
    # and every label[for] must point at a real control
    assert label_fors <= control_ids, f"labels pointing at missing ids: {label_fors - control_ids}"


# ---------------------------------------------------------------------------
# Mobile keyboards: autocomplete / inputmode
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field_id,attr,value", [
    ("f-name", "autocomplete", "name"),
    ("f-phone", "autocomplete", "tel"),
    ("f-phone", "inputmode", "tel"),
    ("f-email", "autocomplete", "email"),
    ("f-address", "autocomplete", "street-address"),
    ("f-postal-code", "autocomplete", "postal-code"),
    ("f-postal-code", "inputmode", "numeric"),
])
def test_demo_form_fields_have_mobile_keyboard_hints(field_id, attr, value):
    html = _form_html()
    m = re.search(rf'<input[^>]*\bid="{field_id}"[^>]*>', html)
    assert m, f"field #{field_id} not found"
    assert f'{attr}="{value}"' in m.group(0), f"#{field_id} missing {attr}={value!r}"


# ---------------------------------------------------------------------------
# Works without JavaScript
# ---------------------------------------------------------------------------

def test_demo_form_has_a_real_no_js_action_and_no_novalidate():
    html = _form_html()
    m = re.search(r'<form\b[^>]*>', html)
    assert m, "no <form> tag found"
    tag = m.group(0)
    assert 'action="/demo/form"' in tag
    assert 'method="post"' in tag
    assert "novalidate" not in tag  # HTML5 required/type/pattern must gate without JS


def test_demo_form_required_fields_use_native_html5_validation():
    html = _form_html()
    for field_id in ("f-name", "f-phone"):
        m = re.search(rf'<input[^>]*\bid="{field_id}"[^>]*>', html)
        assert "required" in m.group(0), f"#{field_id} should be required"
    assert re.search(r'<select[^>]*\bid="f-category"[^>]*\brequired\b', html)
    assert re.search(r'<input[^>]*name="gdpr"[^>]*\brequired\b', html)


def test_demo_form_noscript_reveals_every_step():
    """Without the wizard script, all three <section class="step"> (including the
    submit button + required consent checkbox in step 3) must be reachable."""
    html = _form_html()
    m = re.search(r"<noscript><style>(.*?)</style></noscript>", html)
    assert m, "expected a <noscript><style> fallback forcing every step visible"
    css = m.group(1)
    assert ".step{display:block!important}" in css.replace(" ", "")


# ---------------------------------------------------------------------------
# Performance: deferred scripts, no CDN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("html_fn", [_homepage_html, _form_html])
def test_scripts_are_deferred(html_fn):
    html = html_fn()
    for tag in re.findall(r"<script\b[^>]*\bsrc=[^>]*>", html):
        assert "defer" in tag, f"script tag missing defer: {tag}"


@pytest.mark.parametrize("html_fn", [_homepage_html, _form_html])
def test_no_external_cdn_hosts(html_fn):
    html = html_fn()
    for tag in re.findall(r'<(?:script|link)\b[^>]*\b(?:src|href)="(https?://[^"]+)"', html):
        host = re.sub(r"^https?://", "", tag).split("/")[0]
        assert host in ALLOWED_STYLESHEET_HOSTS + ALLOWED_SCRIPT_HOSTS, f"unexpected external host: {host}"


# ---------------------------------------------------------------------------
# Images (future-proofing: no <img> ships today, but if one is added it must
# not cause layout shift or be inaccessible to screen readers)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("html_fn", [_homepage_html, _form_html])
def test_any_img_tag_has_alt_and_dimensions(html_fn):
    html = html_fn()
    for tag in re.findall(r"<img\b[^>]*>", html):
        assert "alt=" in tag, f"<img> missing alt: {tag}"
        assert "width=" in tag and "height=" in tag, f"<img> missing width/height: {tag}"


# ---------------------------------------------------------------------------
# Language + mobile header regression (nav overflow bug fixed 2026-09-05)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("html_fn", [_homepage_html, _form_html])
def test_lang_is_swedish(html_fn):
    assert '<html lang="sv">' in html_fn()


def test_homepage_nav_cta_hidden_below_breakpoint_with_sufficient_specificity():
    """Regression: `.nav-cta{display:none}` was silently overridden by the later,
    equal-specificity `.btn{display:inline-flex}` rule, so the header CTA rendered
    on phones and forced the whole page to overflow horizontally. Needs either a
    higher-specificity selector or source order after .btn; we use specificity."""
    html = _homepage_html()
    assert "a.nav-cta{display:none}" in html
    assert "nav.links{display:none" in html
    assert "@media (min-width:640px){nav.links{display:flex}}" in html


def test_demo_form_post_without_js_is_not_rejected_by_csrf(client):
    """The no-JS fallback gave the form action="..." method="post". Django's CSRF
    middleware rejects a POST with no token with 403 Forbidden — which would be WORSE
    for a no-JS visitor than the original "can't submit at all". The form must carry
    {% csrf_token %} and the POST must come back as a normal page."""
    from django.urls import reverse
    body = client.get(reverse("demo-form")).content.decode("utf-8")
    assert "csrfmiddlewaretoken" in body, "POST form is missing {% csrf_token %} → 403 without JS"
    resp = client.post(reverse("demo-form"), {"name": "Test"})
    assert resp.status_code == 200, f"no-JS submit returned {resp.status_code}, not a page"


def test_customer_pages_stay_swedish_regardless_of_operator_language(client):
    """Deliberate asymmetry, decided 2026-09-05 after an i18n survey.

    The DASHBOARD is switchable (the operator asked for English + a switcher). The PUBLIC
    pages are not: they serve Swedish customers of a Swedish plumbing firm, and one of the
    strings is the GDPR consent sentence — the text the customer legally agrees to. With
    LANGUAGE_CODE="en", wrapping these in {% trans %} would serve an English marketing page
    AND an English consent line to any visitor whose browser omits Accept-Language: sv.

    So these pages hold their Swedish copy directly. This test fails if someone wraps them
    in {% trans %} without also pinning the view's locale — which is the accident to catch.
    """
    from django.utils import translation
    with translation.override("en"):
        for url in ("/demo/homepage", "/demo/form"):
            body = client.get(url).content.decode("utf-8")
            assert 'lang="sv"' in body, f"{url} lost its Swedish lang attribute"
            assert "Värmepump" in body or "värmepump" in body, (
                f"{url} rendered non-Swedish copy under an English locale — customer-facing "
                "pages must not follow the operator's language choice"
            )
