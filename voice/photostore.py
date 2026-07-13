"""PhotoContext store — the WhatsApp ⇄ live-call join keyed by peppered ``phone_hash``.

``upsert`` records extracted facts; ``bind_call`` links a WhatsApp identity to a live call's
controlUrl (stamped by ``request_photos`` before the photo arrives); ``maybe_push_to_live_call``
POSTs the confirmation into the live call the moment vision finishes (design §5).
"""

from __future__ import annotations

import logging

from django.utils import timezone

from voice import callcontrol
from voice.models import PhotoContext, VapiCall

logger = logging.getLogger(__name__)

MAX_AGE_S = 900  # 15 min — a photo older than this doesn't bind to a live call


def upsert(phone_hash: str, *, facts: dict, image_sha256: str, n_photos: int = 1) -> PhotoContext:
    """Idempotent upsert on ``(phone_hash, image_sha256)`` — a re-delivered photo updates in place.
    Inherits the call binding (call_id + control_url) from any placeholder ``request_photos`` left."""
    call_id, control_url = _binding_for(phone_hash)
    pc, _created = PhotoContext.objects.update_or_create(
        phone_hash=phone_hash, image_sha256=image_sha256,
        defaults={"facts": facts, "n_photos": n_photos,
                  "call_id": call_id, "control_url": control_url, "delivered": False},
    )
    return pc


def _binding_for(phone_hash: str) -> tuple[str, str]:
    """The most recent (call_id, control_url) bound to this phone_hash — from a live VapiCall first,
    then a request_photos placeholder PhotoContext."""
    vc = (VapiCall.objects.filter(caller_phone_hash=phone_hash)
          .exclude(control_url="").order_by("-created_at").first())
    if vc:
        return vc.call_id, vc.control_url
    pc = (PhotoContext.objects.filter(phone_hash=phone_hash)
          .exclude(control_url="").order_by("-created_at").first())
    if pc:
        return pc.call_id, pc.control_url
    return "", ""


def latest_for(phone_hash: str, *, max_age_s: int = MAX_AGE_S) -> PhotoContext | None:
    cutoff = timezone.now() - timezone.timedelta(seconds=max_age_s)
    return (PhotoContext.objects.filter(phone_hash=phone_hash, created_at__gte=cutoff)
            .order_by("-created_at").first())


def bind_call(phone_hash: str, call_id: str, control_url: str) -> None:
    """Stamp a placeholder binding so a photo that arrives knows which live call to push into.
    Called by ``request_photos`` before the photo exists."""
    if not phone_hash:
        return
    PhotoContext.objects.update_or_create(
        phone_hash=phone_hash, image_sha256="",
        defaults={"call_id": call_id or "", "control_url": control_url or "", "facts": {}},
    )


def maybe_push_to_live_call(phone_hash: str) -> bool:
    """If a live call is bound to this phone_hash and a fresh, undelivered photo exists, push the
    extracted facts into the call via ``add-message``. Returns True iff a push fired.

    Skipped (returns False) when no controlUrl was captured — the agent falls back to
    ``check_photos`` on the caller's next cue."""
    pc = (PhotoContext.objects.filter(phone_hash=phone_hash, delivered=False)
          .exclude(image_sha256="").order_by("-created_at").first())
    if pc is None or not pc.control_url:
        return False

    note = _confirmation_note(pc)
    pushed = callcontrol.add_message(pc.control_url, note, role="system", trigger_response=True)
    if pushed:
        pc.delivered = True
        pc.save(update_fields=["delivered", "updated_at"])
    return pushed


def _confirmation_note(pc: PhotoContext) -> str:
    """The structured system note injected into the live call. The agent renders it in persona."""
    facts = pc.facts or {}
    brand = facts.get("brand") or "unknown"
    model = facts.get("model") or "unknown"
    code = facts.get("error_code") or "none"
    n = int(pc.n_photos or 1)
    if model == "unknown":
        return (f"[PHOTO_CONTEXT] received {n} photo(s) from the caller's WhatsApp, but the model "
                "could not be read. Tell the caller the photo was unclear and ask them to re-send a "
                "clear shot of the rating plate. Do not claim to see the machine.")
    return (f"[PHOTO_CONTEXT] received {n} photo(s) from the caller's WhatsApp. "
            f"Extracted: manufacturer={brand}, model={model}, error_code={code}. "
            "Briefly confirm in Swedish what you can see, then continue troubleshooting or "
            "escalation using these facts. Do not read the serial number aloud.")
