"""The Vapi webhook contract — POST /api/voice/vapi (design §3.1, FR-PHN).

Every Vapi server message arrives as ``{"message": {...}}``; we dispatch on ``message.type``:
``tool-calls`` | ``status-update`` | ``end-of-call-report``. Ported from budtender's dispatch
skeleton, single-tenant (no store routing).

Security: ``signing.verify_signature`` runs FIRST and the path fails closed — a missing/bad
signature returns 401 BEFORE any handler parses intent (DEBUG-only dev bypass). CSRF-exempt because
it is HMAC/secret-authed, not cookie-authed.

status-update captures ``call.monitor.controlUrl`` onto the ``VapiCall`` row (and forward to any
PhotoContext already bound) — the mid-call photo push target. end-of-call-report is the durable,
idempotent record (upsert on ``call_id`` so a re-delivery never double-writes).
"""

from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from voice import guardrails, outcomes, signing
from voice.tools import dispatch as dispatch_tool

logger = logging.getLogger(__name__)


def _parse_body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except Exception:  # noqa: BLE001
        return {}


def _caller_number(message: dict) -> str:
    call = message.get("call") or {}
    customer = call.get("customer") or {}
    return str(customer.get("number") or "")


def _control_url(message: dict) -> str:
    call = message.get("call") or {}
    monitor = call.get("monitor") or {}
    return str(monitor.get("controlUrl") or monitor.get("controlURL") or "")


# ── tolerant tool-call extraction (cross-version normalizer) ───────────────────
def _extract_tool_calls(message: dict) -> list[dict]:
    raw = message.get("toolCalls") or message.get("toolCallList")
    if not isinstance(raw, list):
        return []
    normalized: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        fn = entry.get("function") or {}
        name = fn.get("name") or entry.get("name") or ""
        args = fn.get("arguments")
        if args is None:
            args = entry.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:  # noqa: BLE001
                args = {}
        if not isinstance(args, dict):
            args = {}
        normalized.append({
            "id": entry.get("id") or entry.get("toolCallId") or "",
            "name": name, "arguments": args,
        })
    return normalized


# ── Per-event handlers ─────────────────────────────────────────────────────────
def handle_tool_calls(message: dict) -> JsonResponse:
    """Route each tool call through the registry and return the Vapi tool-result envelope."""
    from crm.models import phone_hash
    from voice.models import VapiCall

    call = message.get("call") or {}
    call_id = call.get("id", "")
    caller = _caller_number(message)
    # control_url: prefer the live message; else the one captured on the VapiCall row.
    control_url = _control_url(message)
    if not control_url and call_id:
        vc = VapiCall.objects.filter(call_id=call_id).first()
        control_url = vc.control_url if vc else ""

    ctx = {
        "call_id": call_id,
        "caller_phone": caller,          # transient — hashed by tools, never persisted raw
        "phone_hash": phone_hash(caller),
        "control_url": control_url,
    }

    results = []
    for tc in _extract_tool_calls(message):
        ctx["tool_call_id"] = tc["id"]
        result = dispatch_tool(tc["name"], tc["arguments"], ctx)
        guardrails.assert_no_leak(result)
        results.append({"toolCallId": tc["id"], "result": result})
        _log_tool_call(call_id, tc, tc["arguments"], result)
    return JsonResponse({"results": results})


def _log_tool_call(call_id: str, tc: dict, args: dict, result) -> None:
    """Persist one tool invocation (args PII-masked). Best-effort — never breaks the response."""
    if not call_id:
        return
    from voice.models import ToolCallLog

    try:
        ToolCallLog.objects.update_or_create(
            call_id=call_id, tool_call_id=(tc.get("id") or ""), name=(tc.get("name") or ""),
            defaults={
                "args": guardrails.redact_pii(args),
                "result": guardrails.redact_pii(result),
                "source": "webhook",
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("tool-call log failed for %s/%s", call_id, tc.get("name"), exc_info=True)


def handle_status_update(message: dict) -> JsonResponse:
    """Capture ``monitor.controlUrl`` (the mid-call push target) + the last status. Acks 200."""
    from crm.models import phone_hash
    from voice.models import PhotoContext, VapiCall

    call = message.get("call") or {}
    call_id = call.get("id", "")
    if not call_id:
        return JsonResponse({})

    control_url = _control_url(message)
    status = str(message.get("status") or "")
    caller = _caller_number(message)
    ph = phone_hash(caller)

    vc, _ = VapiCall.objects.get_or_create(call_id=call_id)
    fields = []
    if control_url and vc.control_url != control_url:
        vc.control_url = control_url
        fields.append("control_url")
    if ph and not vc.caller_phone_hash:
        vc.caller_phone_hash = ph
        fields.append("caller_phone_hash")
    if status and vc.status != status:
        vc.status = status
        fields.append("status")
    if call.get("assistantId") and not vc.assistant_id:
        vc.assistant_id = call.get("assistantId")
        fields.append("assistant_id")
    if fields:
        fields.append("updated_at")
        vc.save(update_fields=fields)

    # Forward a freshly-captured controlUrl onto any PhotoContext already bound to this caller.
    if control_url and ph:
        PhotoContext.objects.filter(phone_hash=ph, control_url="").update(
            call_id=call_id, control_url=control_url
        )
    return JsonResponse({})


def handle_end_of_call_report(message: dict) -> JsonResponse:
    """Durable, idempotent record (upsert on call_id) + deterministic outcome. Always acks 200."""
    from crm.models import phone_hash
    from voice.models import VapiCall

    call = message.get("call") or {}
    call_id = call.get("id", "")
    if not call_id:
        return JsonResponse({})

    caller = _caller_number(message)
    transcript = message.get("transcript", "") or ""
    duration = message.get("durationSeconds")
    outcome, reason = outcomes.classify_outcome(message, transcript)

    VapiCall.objects.update_or_create(
        call_id=call_id,
        defaults={
            "caller_phone_hash": phone_hash(caller),
            "transcript": guardrails.redact_pii(transcript)[:20000],
            "duration_s": int(duration) if isinstance(duration, (int, float)) else None,
            "outcome": outcome,
            "escalated": outcome in ("escalation", "callback"),
            "reason": reason,
            "ai_summary": guardrails.redact_pii((message.get("summary") or ""))[:4000],
            "assistant_id": call.get("assistantId", "") or "",
        },
    )
    return JsonResponse({})


_DISPATCH = {
    "tool-calls": handle_tool_calls,
    "status-update": handle_status_update,
    "end-of-call-report": handle_end_of_call_report,
}


@csrf_exempt
@require_POST
def vapi_webhook(request):
    """The single Vapi webhook entrypoint. HMAC/secret-verify FIRST (fail-closed 401), then
    dispatch on ``message.type``."""
    ok, why = signing.verify_signature(request)
    if not ok:
        logger.warning("vapi webhook rejected: %s", why)  # never logs the secret
        return JsonResponse({"error": "unauthorized"}, status=401)

    body = _parse_body(request)
    message = body.get("message") or {}
    handler = _DISPATCH.get(message.get("type", ""))
    if handler is None:
        return JsonResponse({"error": "unknown_type", "type": message.get("type", "")}, status=400)
    return handler(message)
