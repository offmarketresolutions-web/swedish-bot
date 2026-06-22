"""Widget-facing chat API (plan §10). Anonymous: the conversation public_id is the
session token. SSE streaming. Hardened (V2 §S6/S7): per-IP/session rate limits,
image re-encode + quota."""
from __future__ import annotations

import json

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from chat.models import Conversation
from chat.orchestrator import open_conversation, process_turn
from chat.uploads import sanitize_image


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
    lang = (data.get("language") or "en")[:5]
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
