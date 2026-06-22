"""Minimal CORS for the embeddable widget (plan §10) + a LOCAL/DEMO open-admin
shim. No third-party dependency (ponytail)."""
import logging

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)


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


class DemoAutoLoginMiddleware:
    """LOCAL/DEMO ONLY: when settings.DEMO_OPEN_ADMIN is true, transparently log in
    as a superuser so /admin and /dashboard need no credentials. FAIL-SAFE: a no-op
    unless the flag is explicitly set (default off). NEVER enable in production."""

    def __init__(self, get_response):
        self.get_response = get_response
        if bool(getattr(settings, "DEMO_OPEN_ADMIN", False)):
            logger.warning("DEMO_OPEN_ADMIN is ON — /admin and /dashboard auth is BYPASSED. "
                           "Local/demo use only; never ship this enabled.")

    def __call__(self, request):
        # Read the flag live (not cached) so it's fail-safe and testable.
        if getattr(settings, "DEMO_OPEN_ADMIN", False) and not request.user.is_authenticated:
            from django.contrib.auth import get_user_model, login
            user = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("id").first()
            if user:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)
