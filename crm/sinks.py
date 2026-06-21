"""Pluggable lead sinks (plan §9). v1 ships DB (always) + email. Webhook + the
WordPress /offert POST are built but disabled by config until the client provides
URL + form field names. Each sink is independent — one failing never blocks the
others (resolves crit 0.6/1.5). A cron re-send sweep retries non-success rows.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import send_mail

from crm.models import LeadDelivery

logger = logging.getLogger(__name__)


class LeadSink:
    name = "base"

    def enabled(self) -> bool:
        return True

    def deliver(self, service_request) -> None:
        raise NotImplementedError


class DBSink(LeadSink):
    """Always succeeds — the ServiceRequest row IS the durable record."""

    name = "db"

    def deliver(self, service_request) -> None:
        return None


class EmailSink(LeadSink):
    name = "email"

    def enabled(self) -> bool:
        return bool(settings.LEAD_EMAIL_TO)

    def deliver(self, service_request) -> None:
        from chat.sanitize import clean_lead_field as f  # S1: strip CR/LF / control / oversize
        s = service_request.session
        c = s.customer
        body = (
            "New lead from the Nordland VVS assistant.\n\n"
            f"Equipment: {f(s.manufacturer, 40)} {f(s.model, 40)} ({f(s.error_code, 16) or 'no code'})\n"
            f"Severity: {f(s.severity, 16)}   Problem: {f(str(s.problem_category or ''), 40)}\n"
            f"Customer: {f(c.name) if c else ''} {f(c.phone, 32) if c else ''} {f(c.email) if c else ''}\n"
            f"Address: {f(c.address) if c else ''} {f(c.postal_code, 20) if c else ''}\n"
            f"Reason: {f(service_request.escalation_reason, 40)}\n\n"
            f"Summary:\n{s.ai_summary}\n"
        )
        subject = f(f"[Nordland lead] {s.manufacturer} {s.model} — {s.severity}", 120)
        send_mail(
            subject=subject, message=body, from_email=settings.LEAD_EMAIL_FROM,
            recipient_list=[settings.LEAD_EMAIL_TO], fail_silently=False,
        )


class WebhookSink(LeadSink):
    name = "webhook"

    def enabled(self) -> bool:
        import os
        return os.environ.get("LEAD_WEBHOOK_ENABLED") == "1" and bool(os.environ.get("LEAD_WEBHOOK_URL"))

    def deliver(self, service_request) -> None:
        import os
        url = os.environ["LEAD_WEBHOOK_URL"]
        data = json.dumps(service_request.payload_json).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status >= 300:
                raise RuntimeError(f"webhook HTTP {r.status}")


class WordPressOffertSink(LeadSink):
    """POST into the client's WordPress /offert quote form. DISABLED until the
    client provides the endpoint + field names (plan §15 dependency)."""

    name = "wordpress"

    def enabled(self) -> bool:
        import os
        return os.environ.get("WORDPRESS_OFFERT_ENABLED") == "1" and bool(os.environ.get("WORDPRESS_OFFERT_URL"))

    def deliver(self, service_request) -> None:
        import os
        import urllib.parse

        from chat.sanitize import clean_lead_field as f  # S1
        url = os.environ["WORDPRESS_OFFERT_URL"]
        s = service_request.session
        c = s.customer
        # STUB field map — replace with the real /offert field names from the client.
        fields = {
            "your-name": f(c.name) if c else "",
            "your-phone": f(c.phone, 32) if c else "",
            "your-email": f(c.email) if c else "",
            "your-message": s.ai_summary,
        }
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status >= 300:
                raise RuntimeError(f"wordpress HTTP {r.status}")


SINKS: list[LeadSink] = [DBSink(), EmailSink(), WebhookSink(), WordPressOffertSink()]


def dispatch(service_request) -> dict[str, str]:
    """Fire every sink independently; record one LeadDelivery per (request, sink).
    Returns {sink_name: status}. Never raises — failures are recorded, not fatal."""
    results = {}
    for sink in SINKS:
        delivery, _ = LeadDelivery.objects.get_or_create(
            service_request=service_request, sink=sink.name)
        if delivery.status == "success":
            results[sink.name] = "success"  # idempotent: already delivered
            continue
        delivery.attempts += 1
        if not sink.enabled():
            delivery.status = "skipped"
            delivery.last_error = "disabled or not configured"
        else:
            try:
                sink.deliver(service_request)
                delivery.status = "success"
                delivery.last_error = ""
            except Exception as exc:  # noqa: BLE001
                delivery.status = "failed"
                delivery.last_error = str(exc)[:500]
                logger.warning("lead sink %s failed: %s", sink.name, exc)
        delivery.save()
        results[sink.name] = delivery.status
    return results
