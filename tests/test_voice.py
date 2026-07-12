"""Voice/phone + WhatsApp channel tests — all offline, Gemini + Vapi + Meta mocked.

Covers: Vapi webhook signature fail-closed + DEBUG bypass, end-of-call idempotency, WhatsApp media
→ PhotoContext + CustomerFile(source=whatsapp), mid-call controlUrl push fired/skipped, zero-drift
publish no-op, dry-run Vapi client no-ops without a key, and the server-tool contracts.
"""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from core.services import vapi
from voice import provision, signing
from voice.tools import dispatch

WEBHOOK_URL = "/api/voice/vapi/webhook"
WA_URL = "/api/voice/whatsapp/webhook"


def _jpeg_bytes(color=(120, 120, 120)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "JPEG")
    return buf.getvalue()


def _sign(body: bytes, secret: str) -> str:
    return signing.compute_signature(body, secret)


def _post_vapi(client, message: dict, *, secret="testsecret", sign=True, settings=None):
    if settings is not None:
        settings.VAPI_WEBHOOK_SECRET = secret
    body = json.dumps({"message": message}).encode()
    extra = {}
    if sign:
        extra["HTTP_X_VAPI_SIGNATURE"] = _sign(body, secret)
    return client.post(WEBHOOK_URL, data=body, content_type="application/json", **extra)


# ── 1. Signature fail-closed + DEBUG bypass ────────────────────────────────────
@pytest.mark.django_db
def test_vapi_signature_unconfigured_rejects(client, settings):
    settings.VAPI_WEBHOOK_SECRET = ""
    settings.VOICE_WEBHOOK_DEV_BYPASS = False
    body = json.dumps({"message": {"type": "status-update"}}).encode()
    resp = client.post(WEBHOOK_URL, data=body, content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_vapi_signature_bad_rejects(client, settings):
    settings.VAPI_WEBHOOK_SECRET = "testsecret"
    settings.VOICE_WEBHOOK_DEV_BYPASS = False
    body = json.dumps({"message": {"type": "status-update"}}).encode()
    resp = client.post(WEBHOOK_URL, data=body, content_type="application/json",
                       HTTP_X_VAPI_SIGNATURE="deadbeef")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_vapi_signature_good_accepts(client, settings):
    settings.VOICE_WEBHOOK_DEV_BYPASS = False
    resp = _post_vapi(client, {"type": "status-update",
                               "call": {"id": "c1", "monitor": {"controlUrl": "https://x/c"}}},
                      settings=settings)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_vapi_debug_bypass(client, settings):
    settings.DEBUG = True
    settings.VOICE_WEBHOOK_DEV_BYPASS = True
    settings.VAPI_WEBHOOK_SECRET = ""  # unset — bypass still allows in DEBUG
    body = json.dumps({"message": {"type": "status-update", "call": {"id": "c9"}}}).encode()
    resp = client.post(WEBHOOK_URL, data=body, content_type="application/json")
    assert resp.status_code == 200


# ── 2. status-update captures controlUrl; end-of-call idempotency ──────────────
@pytest.mark.django_db
def test_status_update_captures_control_url(client, settings):
    from voice.models import VapiCall

    _post_vapi(client, {"type": "status-update", "status": "in-progress",
                        "call": {"id": "call-1", "monitor": {"controlUrl": "https://vapi/ctl/1"},
                                 "customer": {"number": "+46701112233"}}}, settings=settings)
    vc = VapiCall.objects.get(call_id="call-1")
    assert vc.control_url == "https://vapi/ctl/1"
    assert vc.caller_phone_hash


@pytest.mark.django_db
def test_end_of_call_idempotent(client, settings):
    from voice.models import VapiCall

    msg = {"type": "end-of-call-report",
           "call": {"id": "call-eocr", "customer": {"number": "+46701112233"}},
           "transcript": "hej", "durationSeconds": 42}
    _post_vapi(client, msg, settings=settings)
    _post_vapi(client, msg, settings=settings)  # duplicate delivery
    assert VapiCall.objects.filter(call_id="call-eocr").count() == 1


# ── 3. WhatsApp media → PhotoContext + CustomerFile(source=whatsapp) ───────────
@pytest.mark.django_db
def test_whatsapp_ingest_creates_photocontext_and_file(mock_gemini):
    from crm.models import CustomerFile, phone_hash
    from voice import whatsapp
    from voice.models import PhotoContext

    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "Greenline HE",
                                       "serial": "", "error_code": "E21"}
    pc = whatsapp.ingest_photo("46701112233", _jpeg_bytes())
    assert pc is not None
    ph = phone_hash("+46701112233")
    stored = PhotoContext.objects.filter(phone_hash=ph).exclude(image_sha256="").first()
    assert stored.facts["model"] == "Greenline HE"
    assert stored.facts["error_code"] == "E21"
    cf = CustomerFile.objects.filter(source="whatsapp").first()
    assert cf is not None and cf.kind == "photo"


# ── 4. controlUrl push fired when live call exists / skipped when not ──────────
@pytest.mark.django_db
def test_push_fires_when_live_call_bound(mock_gemini, monkeypatch):
    from crm.models import phone_hash
    from voice import callcontrol, whatsapp
    from voice.models import PhotoContext, VapiCall

    pushed = {}
    monkeypatch.setattr(callcontrol, "add_message",
                        lambda url, content, **kw: pushed.update(url=url, content=content) or True)
    ph = phone_hash("+46701112233")
    VapiCall.objects.create(call_id="live-1", caller_phone_hash=ph,
                            control_url="https://vapi/ctl/live-1")
    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "Geo 412C",
                                       "serial": "", "error_code": ""}
    whatsapp.ingest_photo("46701112233", _jpeg_bytes())
    assert pushed.get("url") == "https://vapi/ctl/live-1"
    assert PhotoContext.objects.get(phone_hash=ph, image_sha256__gt="").delivered is True


@pytest.mark.django_db
def test_push_skipped_when_no_live_call(mock_gemini, monkeypatch):
    from voice import callcontrol, whatsapp
    from voice.models import PhotoContext

    calls = []
    monkeypatch.setattr(callcontrol, "add_message", lambda *a, **k: calls.append(a) or True)
    mock_gemini.responses["vision"] = {"manufacturer": "IVT", "model": "Geo 412C",
                                       "serial": "", "error_code": ""}
    whatsapp.ingest_photo("46700000000", _jpeg_bytes())
    assert calls == []  # no controlUrl bound → no push
    assert PhotoContext.objects.exclude(image_sha256="").first().delivered is False


# ── 5. zero-drift publish no-op ────────────────────────────────────────────────
@pytest.mark.django_db
def test_zero_drift_publish_noop(settings):
    from dashboard import publish

    settings.VAPI_PRIVATE_KEY = ""  # forces dry-run provisioning
    report = provision.provision_all(dry_run=True)
    assert report.errors == 0
    # A re-preview with no edits is a proven no-op (hash matches the stored provision hash).
    prev = publish.preview()
    assert prev.action == "nodrift"
    assert prev.drift is False


# ── 6. dry-run Vapi client no-ops without a key ────────────────────────────────
@pytest.mark.django_db
def test_dry_run_client_records_without_key(settings):
    settings.VAPI_PRIVATE_KEY = ""
    import os
    os.environ.pop("VAPI_PRIVATE_KEY", None)
    assert vapi.configured() is False
    report = provision.provision_all(dry_run=False)  # auto-engages dry-run
    assert report.dry_run is True
    assert report.ok is True
    assert vapi.recorded_calls  # writes were recorded, none issued


# ── 7. Tool endpoint contracts ─────────────────────────────────────────────────
@pytest.mark.django_db
def test_request_photos_unconfigured_falls_back(settings):
    settings.WA_ACCESS_TOKEN = ""
    out = dispatch("request_photos", {}, {"call_id": "c", "caller_phone": "+46701112233",
                                          "phone_hash": "abc", "control_url": ""})
    assert out["sent"] is False and "fallback" in out


@pytest.mark.django_db
def test_check_photos_contract(mock_gemini):
    from crm.models import phone_hash
    from voice import photostore

    ph = phone_hash("+46701112233")
    assert dispatch("check_photos", {}, {"phone_hash": ph})["received"] == 0
    photostore.upsert(ph, facts={"brand": "IVT", "model": "Geo 412C", "error_code": "E9"},
                      image_sha256="s1", n_photos=2)
    out = dispatch("check_photos", {}, {"phone_hash": ph})
    assert out["received"] == 2 and out["model"] == "Geo 412C"


@pytest.mark.django_db
def test_identify_machine_unknown(mock_gemini):
    out = dispatch("identify_machine", {"free_text": "zzz nonexistent unit"}, {})
    assert out["identified"] is False


@pytest.mark.django_db
def test_kb_lookup_escalates_without_machine(mock_gemini):
    out = dispatch("kb_lookup", {"problem": "no heat and a weird noise"}, {})
    assert out["can_help"] is False and out["suggest_escalate"] is True


@pytest.mark.django_db
def test_schedule_callback_needs_phone():
    assert dispatch("schedule_callback", {}, {})["need"] == "phone"


@pytest.mark.django_db
def test_create_lead_idempotent(mock_gemini):
    from crm.models import ServiceRequest

    ctx = {"call_id": "lead-call", "caller_phone": "+46701112233",
           "phone_hash": "", "control_url": ""}
    args = {"problem": "no heat", "brand": "IVT", "model": "Geo 412C",
            "error_code": "E9", "reason": "phone_escalation"}
    r1 = dispatch("create_lead", dict(args), dict(ctx))
    r2 = dispatch("create_lead", dict(args), dict(ctx))
    assert r1["created"] is True and r2["created"] is False
    assert r1["lead_id"] == r2["lead_id"]
    assert ServiceRequest.objects.count() == 1


@pytest.mark.django_db
def test_unknown_tool_contract():
    assert dispatch("nope", {}, {})["error"] == "unknown_tool"


# ── WhatsApp webhook: GET verify + POST fail-closed ────────────────────────────
@pytest.mark.django_db
def test_whatsapp_get_verify(client, settings):
    settings.WA_VERIFY_TOKEN = "vtok"
    resp = client.get(WA_URL, {"hub.mode": "subscribe", "hub.verify_token": "vtok",
                               "hub.challenge": "12345"})
    assert resp.status_code == 200 and resp.content == b"12345"


@pytest.mark.django_db
def test_whatsapp_post_unconfigured_rejects(client, settings):
    settings.WA_APP_SECRET = ""
    settings.VOICE_WEBHOOK_DEV_BYPASS = False
    resp = client.post(WA_URL, data=b"{}", content_type="application/json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_whatsapp_post_good_sig_accepts(client, settings):
    settings.WA_APP_SECRET = "appsecret"
    settings.VOICE_WEBHOOK_DEV_BYPASS = False
    body = json.dumps({"entry": []}).encode()
    sig = "sha256=" + signing.compute_signature(body, "appsecret")
    resp = client.post(WA_URL, data=body, content_type="application/json",
                       HTTP_X_HUB_SIGNATURE_256=sig)
    assert resp.status_code == 200
