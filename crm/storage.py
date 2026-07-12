"""Per-customer folder storage for the Customer File Hub.

Materializes media/customers/<id>/{uploads,invoices,docs}/ on local disk and
registers every file as a CustomerFile row. All chat photo uploads for an
identified customer, plus staff dashboard uploads (invoices/docs), flow through
register_file — one place that dedups by content hash, places the file in the
right per-customer folder, and fires the optional n8n Google Drive mirror sink.

Local disk only (Karpathy-minimal) — no S3/GCS abstraction. The n8n sink is the
single outbound integration, and it is off by default.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile

from crm.models import FILE_FOLDERS, CustomerFile

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def customer_root(customer) -> Path:
    """Absolute path to a customer's folder root (media/customers/<id>)."""
    return Path(settings.MEDIA_ROOT) / "customers" / str(customer.pk)


def ensure_folders(customer) -> Path:
    """Create the customer's {uploads,invoices,docs} folders on disk. Idempotent.
    Returns the customer folder root."""
    root = customer_root(customer)
    for sub in FILE_FOLDERS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def infer_kind(filename: str, content_type: str = "") -> str:
    name, ct = (filename or "").lower(), (content_type or "").lower()
    if ct.startswith("image/") or name.endswith(_IMAGE_EXTS):
        return "photo"
    if name.endswith(".pdf") or "pdf" in ct:
        return "pdf"
    return "other"


def register_file(customer, *, content: bytes, filename: str, folder: str = "uploads",
                  source: str = "staff", kind: str | None = None,
                  content_type: str = "", sha256: str | None = None,
                  source_message=None, mirror: bool = True) -> tuple[CustomerFile, bool]:
    """Register a file on a customer's profile in the given folder. Dedups by
    (customer, sha256): a repeat content hash returns the existing row, created=False,
    and is NOT re-mirrored. On a new file, materializes the folder, saves the bytes
    into media/customers/<id>/<folder>/, and fires the n8n mirror sink (best-effort).

    Returns (customer_file, created)."""
    if folder not in FILE_FOLDERS:
        folder = "uploads"
    sha = sha256 or hashlib.sha256(content).hexdigest()
    existing = CustomerFile.objects.filter(customer=customer, sha256=sha).first()
    if existing:
        return existing, False

    ensure_folders(customer)
    cf = CustomerFile(
        customer=customer, folder=folder, source=source, sha256=sha,
        kind=kind or infer_kind(filename, content_type),
        original_name=(filename or "")[:255], source_message=source_message,
    )
    # customer_id + folder are set, so customer_file_path routes into the right folder.
    cf.file.save(filename or f"{sha[:12]}.bin", ContentFile(content), save=True)

    if mirror:
        from crm import file_sink
        try:
            link = file_sink.mirror_customer_file(cf)
            if link:
                cf.drive_url = link[:200]
                cf.save(update_fields=["drive_url"])
        except Exception:  # noqa: BLE001 — mirror is glue, never block registration
            pass
    return cf, True
