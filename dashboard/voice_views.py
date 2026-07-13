"""Dashboard voice/phone control-plane pages (additive to dashboard/views.py).

- credentials catalog (masked, DB-stored, live-applied)
- phone config: assistant status + publish-with-diff button + recent calls + tool-call log
"""

from __future__ import annotations

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from dashboard import credentials


def _toast(type_: str, message: str) -> str:
    return json.dumps({"toast": {"type": type_, "message": message}})


@staff_member_required
def voice_credentials(request):
    """Grouped credentials catalog. POST a single ``name``/``value`` to set + live-apply it."""
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        value = (request.POST.get("value") or "").strip()
        if not credentials.is_known(name):
            resp = redirect("dash-voice-credentials")
            resp["HX-Trigger"] = _toast("error", f"Unknown credential: {name}")
            return resp
        credentials.set_credential(name, value)
        resp = redirect("dash-voice-credentials")
        resp["HX-Trigger"] = _toast("success", f"Saved {name} (live, no redeploy).")
        return resp
    return render(request, "dashboard/voice_credentials.html",
                  {"groups": credentials.catalog_with_values()})


@staff_member_required
def voice_phone(request):
    """Assistant status + publish diff + recent calls + tool-call log."""
    from core.services import vapi
    from dashboard import publish
    from voice.models import ToolCallLog, VapiCall, VapiObject

    prev = publish.preview()
    asst = VapiObject.objects.filter(kind="assistant").first()
    ctx = {
        "preview": prev,
        "payload_json": json.dumps(prev.payload, indent=2, ensure_ascii=False),
        "assistant": asst,
        "vapi_configured": vapi.configured(),
        "recent_calls": VapiCall.objects.all()[:25],
        "tool_calls": ToolCallLog.objects.all().order_by("-created_at")[:25],
    }
    return render(request, "dashboard/voice_phone.html", ctx)


@staff_member_required
@require_POST
def voice_publish(request):
    """Explicit publish button — GET-then-PATCH via the idempotent provisioner (zero-drift no-op)."""
    from dashboard import publish

    result = publish.publish()
    if result.get("error"):
        msg, kind = f"Publish error: {result['error']}", "error"
    elif result["action"] == "skipped":
        msg, kind = f"Publish skipped: {'; '.join(result['warnings']) or 'unprovisioned'}", "error"
    elif result["action"] == "nodrift":
        msg, kind = "Already live in Vapi (no change).", "success"
    else:
        msg, kind = f"Published: assistant {result['action']}.", "success"
    resp = redirect("dash-voice-phone")
    resp["HX-Trigger"] = _toast(kind, msg)
    return resp


@staff_member_required
@require_POST
def voice_fetch_conversation(request, call_id: str):
    """Pull the authoritative transcript + tool calls for a call from Vapi (P6 fetch-back)."""
    from core.services import vapi
    from voice import callfetch

    if not vapi.configured():
        resp = redirect("dash-voice-phone")
        resp["HX-Trigger"] = _toast("error", "Vapi not configured — cannot fetch.")
        return resp
    try:
        out = callfetch.fetch_full_conversation(call_id)
        msg = f"Fetched {out['persisted']['tool_calls']} tool call(s)."
        kind = "success"
    except Exception as exc:  # noqa: BLE001
        msg, kind = f"Fetch failed: {exc}", "error"
    resp = redirect("dash-voice-phone")
    resp["HX-Trigger"] = _toast(kind, msg)
    return resp
