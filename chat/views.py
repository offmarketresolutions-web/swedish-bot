"""Widget-facing chat API (plan §10). Anonymous: the conversation public_id is the
session token. SSE streaming for the assistant turn."""
from __future__ import annotations

import json

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from chat.models import Conversation
from chat.orchestrator import open_conversation, process_turn


def _body(request) -> dict:
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body or b"{}")
        except Exception:  # noqa: BLE001
            return {}
    return request.POST.dict()


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@csrf_exempt
@require_POST
def create_session(request):
    data = _body(request)
    lang = (data.get("language") or "en")[:5]
    conv, greet = open_conversation(lang)
    return JsonResponse({"public_id": str(conv.public_id), **greet})


@csrf_exempt
@require_POST
def post_message(request, public_id):
    conv = get_object_or_404(Conversation, public_id=public_id)
    data = _body(request)
    user_text = data.get("message", "") or ""
    image = request.FILES.get("image")

    def stream():
        result = process_turn(conv, user_text, image=image)
        for ev in result.get("events", []):
            yield _sse(ev)
        yield _sse({"type": "message", "message": result["message"],
                    "chips": result.get("chips", []), "state": result.get("state"),
                    "decision": result.get("decision")})
        yield _sse({"type": "final"})

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp
