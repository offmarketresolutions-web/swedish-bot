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
