"""Core views: health check (plan §13 Phase 1 DONE check) + demo pages."""
from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render

from core.services import gemini


def widget_demo(request):
    """A standalone page that embeds the widget — simulates the WordPress site."""
    return render(request, "widget_demo.html")


def playground(request):
    """Live test console (chat + capability inspector). Local/demo only — hidden in
    production so the FSM internals aren't exposed."""
    if not (getattr(settings, "DEMO_OPEN_ADMIN", False) or settings.DEBUG):
        raise Http404
    return render(request, "playground.html", {
        "embedding_model": gemini.active_embedding_model(),
    })


def healthz(request):
    """Liveness + dependency status: DB reachable + Gemini auth configured."""
    db_ok = True
    db_error = ""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)

    try:
        gem = gemini.health_check()
    except Exception as exc:  # noqa: BLE001
        gem = {"mode": "error", "ready": False, "reason": str(exc)}

    ok = db_ok and gem.get("ready", False)
    return JsonResponse(
        {
            "status": "ok" if ok else "degraded",
            "db": {"ok": db_ok, "error": db_error},
            "gemini": gem,
        },
        status=200 if ok else 503,
    )
