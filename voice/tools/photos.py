"""``request_photos`` + ``check_photos`` server tools — the mid-call WhatsApp photo loop.

``request_photos`` sends a WhatsApp prompt and stamps a PhotoContext binding (call_id + control_url
→ phone_hash) so a photo that arrives can be pushed into the live call. ``check_photos`` is the
cue-based fallback to the automatic push (§5).
"""

from __future__ import annotations

from voice import photostore
from voice.tools import register


@register("request_photos")
def request_photos(args: dict, ctx: dict) -> dict:
    """Text the caller on WhatsApp and register the expectation. Degrades to spoken intake if the
    WhatsApp send fails."""
    from voice import whatsapp

    caller_phone = str(ctx.get("caller_phone") or "")
    phone_hash = ctx.get("phone_hash") or ""
    # Bind the live call to this phone_hash NOW so a photo that arrives can be pushed (§5.4).
    if phone_hash:
        photostore.bind_call(phone_hash, ctx.get("call_id") or "", ctx.get("control_url") or "")

    ok, number = whatsapp.send_photo_prompt(caller_phone)
    if not ok:
        return {"sent": False, "fallback": "read me the model number and the error code"}
    return {"sent": True, "number": number}


@register("check_photos")
def check_photos(args: dict, ctx: dict) -> dict:
    """Report whether the caller's WhatsApp photos have arrived + been read (the push fallback)."""
    phone_hash = ctx.get("phone_hash") or ""
    if not phone_hash:
        return {"received": 0}
    pc = photostore.latest_for(phone_hash)
    if pc is None:
        return {"received": 0}
    facts = pc.facts or {}
    return {
        "received": int(pc.n_photos or 1),
        "brand": facts.get("brand") or "unknown",
        "model": facts.get("model") or "unknown",
        "error_code": facts.get("error_code") or "none",
    }
