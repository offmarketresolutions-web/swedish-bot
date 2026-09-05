"""Widget-facing chat API (plan §10). Anonymous: the conversation public_id is the
session token. SSE streaming. Hardened (V2 §S6/S7): per-IP/session rate limits,
image re-encode + quota."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from chat.models import Conversation
from chat.orchestrator import open_conversation, process_turn
from chat.prefill import read_prefill_token
from chat.uploads import sanitize_image
from crm.models import Session


def _body(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body or b"{}")
        except Exception:  # noqa: BLE001
            return {}
    return request.POST.dict()


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _debug_enabled(request) -> bool:
    """Expose FSM internals (the /playground inspector) only locally — never on the
    public widget endpoint in production."""
    return bool(getattr(settings, "DEMO_OPEN_ADMIN", False) or settings.DEBUG)


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")) or "unknown"


def _rate_ok(key: str, limit: int) -> bool:
    """Simple fixed-window limiter via the cache. Fails open if cache is down."""
    k = f"rl:{key}"
    try:
        n = cache.get(k, 0)
        if n >= limit:
            return False
        cache.set(k, n + 1, settings.RATE_LIMIT_WINDOW)
        return True
    except Exception:  # noqa: BLE001
        return True


@csrf_exempt
@require_POST
def create_session(request):
    if not _rate_ok(f"sess:{_client_ip(request)}", settings.RATE_LIMIT_SESSION):
        return JsonResponse({"error": "rate_limited"}, status=429)
    data = _body(request)
    # Nordland VVS serves Swedish customers: an embed that forgets data-lang, or any
    # direct API caller, must still get a Swedish bot rather than silently switching
    # the whole conversation to English.
    lang = (data.get("language") or settings.CHAT_DEFAULT_LANG)[:5]
    conv, greet = open_conversation(lang)
    return JsonResponse({"public_id": str(conv.public_id), **greet})


@csrf_exempt
@require_POST
def post_message(request, public_id):
    conv = get_object_or_404(Conversation, public_id=public_id)
    if (not _rate_ok(f"msg:{public_id}", settings.RATE_LIMIT_MESSAGE)
            or not _rate_ok(f"msgip:{_client_ip(request)}", settings.RATE_LIMIT_MESSAGE * 3)):
        return JsonResponse({"error": "rate_limited"}, status=429)

    data = _body(request)
    user_text = data.get("message", "") or ""

    # S6: re-encode/validate the uploaded image; reject on failure (raw bytes never stored).
    image, image_error = None, None
    raw_image = request.FILES.get("image")
    if raw_image is not None:
        used = conv.messages.filter(image__isnull=False).exclude(image="").count()
        if used >= settings.MAX_IMAGES_PER_CONVERSATION:
            image_error = "too many images in this conversation"
        else:
            try:
                image = sanitize_image(raw_image)
            except ValidationError as exc:
                image_error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)

    def stream():
        result = process_turn(conv, user_text, image=image)
        for ev in result.get("events", []):
            yield _sse(ev)
        if image_error:
            yield _sse({"type": "notice", "message": f"Image not accepted: {image_error}"})
        frame = {"type": "message", "message": result["message"],
                 "chips": result.get("chips", []), "state": result.get("state"),
                 "decision": result.get("decision")}
        if _debug_enabled(request):
            frame["debug"] = result.get("debug")
        yield _sse(frame)
        yield _sse({"type": "final"})

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


def _prefill_cors(resp):
    resp["Access-Control-Allow-Origin"] = settings.PREFILL_ALLOWED_ORIGIN
    resp["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp["Vary"] = "Origin"
    return resp


@csrf_exempt
def prefill(request, token: str):
    """GET /api/prefill/<token> — read-only snapshot of a session's known facts for
    the owner's real website form to prefill (plan S6/D2). Never invents data: every
    field is either what the bot already captured or omitted."""
    if request.method == "OPTIONS":
        return _prefill_cors(HttpResponse(status=204))
    if request.method != "GET":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    if not _rate_ok(f"prefill:{_client_ip(request)}", settings.RATE_LIMIT_PREFILL):
        return _prefill_cors(JsonResponse({"error": "rate_limited"}, status=429))

    sid = read_prefill_token(token)
    if sid is None:
        return _prefill_cors(JsonResponse({"error": "invalid_or_expired"}, status=404))
    try:
        session = Session.objects.select_related("customer", "category", "problem_category").get(pk=sid)
    except Session.DoesNotExist:
        return _prefill_cors(JsonResponse({"error": "invalid_or_expired"}, status=404))

    # The customer's own words live in Conversation.case_state["slots"] (mined live
    # during the chat) — Session has no "problem" column, so that's the only source
    # for the real problem text / alarm wording (plan S6/D2 follow-up).
    slots = (session.conversation.case_state or {}).get("slots", {}) if session.conversation_id else {}

    technical = {
        "category": session.category.name if session.category else None,
        "subtype": session.problem_category.label if session.problem_category else None,
        "brand": session.manufacturer or None,
        "model": session.model or None,
        "error_code": session.error_code or None,
        "alarm_text": slots.get("alarm_text") or None,
        "problem": slots.get("problem") or None,
        "postal_code": session.postal_code or None,
        "onset": session.onset or None,
        "service_area": {
            "name": session.service_area_name or None,
            "status": session.service_area_status or None,
        } if session.service_area_status else None,
    }
    payload = {"technical": technical, "meta": {"generated_at": datetime.now(timezone.utc).isoformat()}}

    customer = session.customer
    if customer is not None and customer.consent_to_contact:
        payload["contact"] = {
            "name": customer.name or None,
            "phone": customer.phone or None,
            "email": customer.email or None,
            "address": customer.address or None,
        }

    return _prefill_cors(JsonResponse(payload))
