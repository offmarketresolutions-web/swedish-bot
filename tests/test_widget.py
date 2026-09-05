"""Widget assets + demo page (plan §10). The SSE backend the widget calls is
covered by tests/test_api.py."""
import json
from pathlib import Path

import pytest
from django.conf import settings

WIDGET = Path(settings.BASE_DIR) / "static" / "widget"

pytestmark = pytest.mark.django_db


def test_widget_js_calls_the_api_and_reads_data_lang():
    js = (WIDGET / "nordland-widget.js").read_text(encoding="utf-8")
    assert "/api/chat/session" in js
    assert "/message" in js
    assert "data-lang" in js
    assert "text/event-stream" not in js  # uses fetch streaming, not EventSource
    assert "getReader" in js              # reads the SSE stream


def test_i18n_catalogs_share_keys():
    en = json.loads((WIDGET / "i18n" / "en.json").read_text(encoding="utf-8"))
    sv = json.loads((WIDGET / "i18n" / "sv.json").read_text(encoding="utf-8"))
    assert set(en) == set(sv)            # Swedish catalog covers every English key
    assert sv["send"] == "Skicka"


def test_demo_page_embeds_widget(client):
    resp = client.get("/widget-demo")
    assert resp.status_code == 200
    assert b"nordland-widget.js" in resp.content


def test_homepage_demo_renders_and_embeds_widget(client):
    resp = client.get("/demo/homepage")
    assert resp.status_code == 200
    assert b"<script" in resp.content
    assert b"nordland-widget.js" in resp.content


def test_renderchips_renders_a_link_for_url_chips():
    js = (WIDGET / "nordland-widget.js").read_text(encoding="utf-8")
    # url chips render as an <a target=_blank rel=noopener>, not a send-button.
    assert 'c.url' in js
    assert 'noopener' in js


def test_demo_form_page_renders_and_embeds_prefill_snippet(client):
    resp = client.get("/demo/form")
    assert resp.status_code == 200
    assert b"nordland-prefill.js" in resp.content
    assert b'data-testid="service-form"' in resp.content


def test_prefill_snippet_reads_nl_case_param():
    snippet = (Path(settings.BASE_DIR) / "static" / "prefill" / "nordland-prefill.js").read_text(encoding="utf-8")
    assert "nl_case" in snippet
    assert "/api/prefill/" in snippet
    assert "FIELD_MAP" in snippet


# ---- resilience gaps ("works no matter what") ----------------------------

def _js():
    return (WIDGET / "nordland-widget.js").read_text(encoding="utf-8")


def test_widget_aborts_hung_requests_with_a_timeout():
    js = _js()
    assert "AbortController" in js
    assert "ctrl.abort()" in js
    assert "REQUEST_TIMEOUT_MS" in js


def test_widget_offers_retry_on_network_failure_without_forcing_a_retype():
    js = _js()
    # a retry affordance exists and reuses the original request, not a re-typed one
    assert 'setAttribute("data-testid", "widget-retry")' in js
    assert "appendRetryButton" in js
    assert "I18N.retry" in js


def test_widget_backs_off_on_429_instead_of_hammering():
    js = _js()
    assert "429" in js
    assert "RATE_LIMIT_BACKOFF_MS" in js
    assert "rate_limited" in js
    en = json.loads((WIDGET / "i18n" / "en.json").read_text(encoding="utf-8"))
    sv = json.loads((WIDGET / "i18n" / "sv.json").read_text(encoding="utf-8"))
    assert "rate_limited" in en and "rate_limited" in sv
    assert "retry" in en and "retry" in sv


def test_widget_session_persistence_is_guarded_and_restores_thread():
    js = _js()
    assert "sessionStorage.setItem" in js
    assert "sessionStorage.getItem" in js
    assert js.count("catch (e) {}") >= 3  # matchMedia + save() + load() all guarded
    assert "function restore()" in js
    assert "s.convo" in js  # reload restores the persisted transcript, not a blank slate


def test_widget_panel_uses_dvh_with_a_vh_fallback_for_ios_safari():
    js = _js()
    assert "height:100vh;max-height:100vh;height:100dvh;max-height:100dvh" in js


def test_widget_rescrolls_log_when_the_keyboard_opens_on_mobile():
    js = _js()
    assert "visualViewport" in js


def test_widget_traps_tab_and_escape_returns_focus_to_launcher():
    js = _js()
    assert 'e.key === "Escape"' in js
    assert 'e.key !== "Tab"' in js
    assert "launcher.focus()" in js


def test_widget_disables_input_and_shows_busy_state_while_a_turn_is_in_flight():
    js = _js()
    assert "input.disabled = busy" in js
    assert "aria-busy" in js


def test_widget_degrades_when_abortcontroller_is_missing():
    """The widget is deliberately ES5 and already calls fetch() unguarded, but there is a
    real browser window with fetch and WITHOUT AbortController (Chrome 42-65, Safari
    10.1-12). Our demographic runs old devices; `new AbortController()` throwing there
    would kill every send outright. Degrade to an untimed fetch instead of dying."""
    js = (WIDGET / "nordland-widget.js").read_text(encoding="utf-8")
    assert "typeof AbortController" in js, (
        "AbortController is constructed unguarded — on a fetch-capable browser without it, "
        "every message send throws and the widget is dead"
    )
