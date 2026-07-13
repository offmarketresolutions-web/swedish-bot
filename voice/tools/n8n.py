"""``notify_n8n`` — the optional bot-callable n8n trigger tool (ported from budtender/voice).

Fires an n8n automation for a caller-agreed follow-up. Degrade-safe: returns a structured
``{ok: false, reason}`` when n8n is unconfigured or the POST fails — never raises. Not bound to the
assistant by default; the owner adds it from the dashboard.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from django.conf import settings

from voice import guardrails
from voice.tools import register

logger = logging.getLogger(__name__)


@register("notify_n8n")
def notify_n8n(args: dict, ctx: dict) -> dict:
    url = getattr(settings, "N8N_WEBHOOK_URL", "") or ""
    event_type = (args.get("event_type") or "").strip()
    if not event_type:
        return {"ok": False, "reason": "missing event_type"}
    if not url:
        return {"ok": False, "reason": "n8n not configured"}

    payload = {
        "event": "bot_action",
        "event_type": event_type,
        "summary": guardrails.redact_pii((args.get("summary") or "").strip()),
        "call_id": ctx.get("call_id", ""),
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (config-supplied URL)
            if r.status >= 300:
                return {"ok": False, "reason": f"n8n HTTP {r.status}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_n8n POST failed: %s", exc)
        return {"ok": False, "reason": "n8n unreachable"}
    return {"ok": True, "queued": True, "event_type": event_type}
