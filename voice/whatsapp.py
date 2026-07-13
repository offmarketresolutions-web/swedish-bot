"""Meta WhatsApp Cloud API webhook + media intake (design §5.2, FR-WA).

GET  → the Meta subscription handshake (``hub.challenge`` echo, verify-token check).
POST → fail-closed ``X-Hub-Signature-256`` verify, then ACK 200 IMMEDIATELY and finish the
       fetch→sanitize→vision→store→push work on a background thread (return-fast-then-thread; Meta
       retries on a non-200 so a dropped thread just re-runs on redelivery).

The media hot-path stays off n8n. Inbound photos route through ``crm.storage.register_file`` with
``source="whatsapp"`` so they land in the customer folder and mirror to Drive, and the extracted
facts land on a ``PhotoContext`` keyed by the peppered ``phone_hash`` (the cross-channel join).
"""

from __future__ import annotations

import json
import logging
import threading

import httpx
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from crm.models import phone_hash as _phone_hash
from voice import photostore, signing, vision

logger = logging.getLogger(__name__)


def _graph_version() -> str:
    return getattr(settings, "WA_GRAPH_VERSION", "") or "v21.0"


def _wa_token() -> str:
    return getattr(settings, "WA_ACCESS_TOKEN", "") or ""


def _normalize_phone(from_phone: str) -> str:
    """WhatsApp sends the number without a '+'; add one so it hashes identically to the Vapi ANI."""
    p = (from_phone or "").strip()
    if p and not p.startswith("+"):
        p = "+" + p
    return p


# ── The webhook view ────────────────────────────────────────────────────────────
@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        # Meta subscription handshake.
        mode = request.GET.get("hub.mode", "")
        token = request.GET.get("hub.verify_token", "")
        challenge = request.GET.get("hub.challenge", "")
        expected = getattr(settings, "WA_VERIFY_TOKEN", "") or ""
        if mode == "subscribe" and expected and token == expected:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse("forbidden", status=403)

    if request.method != "POST":
        return HttpResponse(status=405)

    ok, why = signing.verify_meta_signature(request)
    if not ok:
        logger.warning("whatsapp webhook rejected: %s", why)  # never logs the secret
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body or b"{}")
    except Exception:  # noqa: BLE001
        body = {}

    jobs = _extract_media_jobs(body)
    # Return fast, finish in a thread (return-fast-then-thread; no Celery/Redis).
    for from_phone, media_id in jobs:
        threading.Thread(target=_process_media, args=(media_id, from_phone), daemon=True).start()
    return JsonResponse({"accepted": len(jobs)})


def _extract_media_jobs(body: dict) -> list[tuple[str, str]]:
    """Pull ``(from_phone, media_id)`` pairs from the Meta inbound payload for image/document msgs."""
    jobs: list[tuple[str, str]] = []
    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for msg in value.get("messages") or []:
                mtype = msg.get("type")
                if mtype not in ("image", "document"):
                    continue
                media = msg.get(mtype) or {}
                media_id = media.get("id")
                from_phone = msg.get("from") or ""
                if media_id and from_phone:
                    jobs.append((from_phone, media_id))
    return jobs


# ── Media fetch + intake ─────────────────────────────────────────────────────────
def fetch_media_bytes(media_id: str) -> bytes | None:
    """Two-step Meta fetch: GET /{media_id} → temp URL (~5 min, Bearer-gated) → download bytes.
    Returns None when WhatsApp isn't configured (dry-run) or on any HTTP error."""
    token = _wa_token()
    if not token or not media_id:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://graph.facebook.com/{_graph_version()}"
    try:
        with httpx.Client(timeout=20.0) as client:
            meta = client.get(f"{base}/{media_id}", headers=headers)
            if meta.status_code >= 300:
                logger.warning("media metadata GET → HTTP %s", meta.status_code)
                return None
            url = (meta.json() or {}).get("url")
            if not url:
                return None
            blob = client.get(url, headers=headers)
            if blob.status_code >= 300:
                logger.warning("media download → HTTP %s", blob.status_code)
                return None
            return blob.content
    except httpx.HTTPError as exc:
        logger.warning("media fetch failed: %s", exc)
        return None


def _process_media(media_id: str, from_phone: str) -> None:
    """Background worker: fetch the media, then run the shared intake. Best-effort; never raises."""
    try:
        data = fetch_media_bytes(media_id)
        if not data:
            return
        ingest_photo(from_phone, data)
    except Exception:  # noqa: BLE001 — a background failure just waits for Meta's redelivery
        logger.warning("whatsapp media processing failed for %s", media_id, exc_info=True)


def ingest_photo(from_phone: str, image_bytes: bytes):
    """Sanitize + OCR one WhatsApp photo, store its facts on a PhotoContext, copy the image to the
    customer folder (source=whatsapp), and push the confirmation into the live call if one is bound.

    Returns the ``PhotoContext`` (or None if the image was invalid). Synchronous — the webhook runs
    it on a thread; tests call it directly."""
    import hashlib

    from django.core.exceptions import ValidationError

    ph = _phone_hash(_normalize_phone(from_phone))
    if not ph:
        return None

    try:
        facts, clean_bytes = vision.extract_nameplate(image_bytes)
    except ValidationError:
        logger.info("whatsapp media was not a valid image; ignored")
        return None

    sha = hashlib.sha256(clean_bytes).hexdigest()
    pc = photostore.upsert(ph, facts=facts, image_sha256=sha, n_photos=1)

    # Copy the sanitized image onto the customer's CRM profile (source=whatsapp) so it lands in the
    # per-customer folder and mirrors to Drive. Best-effort — never block the confirmation push.
    try:
        _store_customer_file(ph, from_phone, clean_bytes, sha)
    except Exception:  # noqa: BLE001
        logger.warning("whatsapp customer-file store failed", exc_info=True)

    # Push the extracted facts into the live call (design §5 option B).
    try:
        photostore.maybe_push_to_live_call(ph)
    except Exception:  # noqa: BLE001
        logger.warning("controlUrl push failed", exc_info=True)
    return pc


def _store_customer_file(phone_hash: str, from_phone: str, content: bytes, sha: str) -> None:
    from crm import storage
    from crm.models import Customer

    cust = Customer.objects.filter(phone_hash=phone_hash).order_by("-created_at").first()
    if cust is None:
        cust = Customer(phone=_normalize_phone(from_phone))
        cust.save()  # save() computes phone_hash from phone
    storage.register_file(
        cust, content=content, filename=f"{sha[:12]}.jpg", folder="uploads",
        source="whatsapp", kind="photo",
    )


# ── Outbound (request_photos) ────────────────────────────────────────────────────
def send_photo_prompt(caller_phone: str) -> tuple[bool, str]:
    """Send the WhatsApp photo-request template to the caller. Returns ``(sent, number)``.
    No-ops to ``(False, number)`` when WhatsApp isn't configured (dry-run) so the agent falls back
    to spoken intake."""
    number = _normalize_phone(caller_phone)
    token = _wa_token()
    phone_number_id = getattr(settings, "WA_PHONE_NUMBER_ID", "") or ""
    template = getattr(settings, "WA_PHOTO_TEMPLATE_NAME", "") or ""
    if not (token and phone_number_id and number):
        return False, number

    base = f"https://graph.facebook.com/{_graph_version()}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    to = number.lstrip("+")
    if template:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "template",
                   "template": {"name": template, "language": {"code": "sv"}}}
    else:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
                   "text": {"body": "Skicka gärna ett foto av enheten och displayen här, "
                                    "så läser jag av modell och felkod."}}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{base}/{phone_number_id}/messages", headers=headers, json=payload)
        if resp.status_code >= 300:
            logger.warning("whatsapp send → HTTP %s", resp.status_code)
            return False, number
        return True, number
    except httpx.HTTPError as exc:
        logger.warning("whatsapp send failed: %s", exc)
        return False, number
