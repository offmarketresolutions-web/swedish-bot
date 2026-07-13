"""The voice (phone/WhatsApp) Django app.

``ready()`` re-asserts DB credential overrides over the ``.env`` defaults at boot (the
dashboard credentials catalog is DB-stored + live-applied), and imports the tool registry so
every ``@register`` handler is bound before the first webhook lands.
"""
from __future__ import annotations

from django.apps import AppConfig


class VoiceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "voice"
    verbose_name = "Voice (phone + WhatsApp)"

    def ready(self) -> None:
        # Re-assert dashboard-stored credentials over .env (no redeploy). Swallows a
        # not-yet-migrated DB so a fresh `migrate` never crashes boot.
        try:
            from dashboard import credentials

            credentials.apply_all()
        except Exception:  # noqa: BLE001 — boot must never fail on a missing table
            pass
        # Bind every tool handler (@register runs at import).
        try:
            import voice.tools  # noqa: F401
        except Exception:  # noqa: BLE001
            pass
