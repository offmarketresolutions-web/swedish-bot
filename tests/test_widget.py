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
