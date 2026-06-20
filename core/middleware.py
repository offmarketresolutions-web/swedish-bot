"""Minimal CORS for the embeddable widget (plan §10). Only /api/ paths, only the
configured origins. Handles preflight. No third-party dependency (ponytail)."""
from django.conf import settings
from django.http import HttpResponse


class WidgetCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin", "")
        allowed = origin in settings.WIDGET_ALLOWED_ORIGINS

        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            resp = HttpResponse(status=204)
        else:
            resp = self.get_response(request)

        if request.path.startswith("/api/") and allowed:
            resp["Access-Control-Allow-Origin"] = origin
            resp["Vary"] = "Origin"
            resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            resp["Access-Control-Allow-Headers"] = "Content-Type"
            resp["Access-Control-Max-Age"] = "86400"
        return resp
