"""Shared manual-ingest logic (plan §8) so the CLI command *and* the staff KB
Manager upload both parse the PDF → token estimate + sha256, not just store bytes.

The specialist loads the PDF into Gemini as inline bytes; parsed_text drives the
token estimate (cache-vs-inline) and gives an audit/searchable copy — NOT RAG.
"""
from __future__ import annotations

import hashlib
import io

from kb.models import MachineDocument

# Staff-gated, but still fail-closed: only real PDFs, bounded size + pages.
MAX_PDF_BYTES = 40 * 1024 * 1024  # 40 MB — manuals are big but not unbounded
MAX_PDF_PAGES = 2000              # cap parse work so a forged PDF can't pin CPU
_PDF_MAGIC = b"%PDF-"


class IngestError(ValueError):
    """Raised on a non-PDF / oversized upload (surfaced to the staff UI)."""


def parse_pdf_text(source, *, max_pages: int = MAX_PDF_PAGES) -> str:
    """source: a filesystem path str or a binary file-like object."""
    try:
        import pdfplumber
    except ImportError:
        return ""
    out = []
    with pdfplumber.open(source) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            out.append(page.extract_text() or "")
    return "\n".join(out)


def ingest_pdf_bytes(machine, data: bytes, filename: str, *, lang: str = "sv",
                     kind: str = "manual", replace: MachineDocument | None = None) -> MachineDocument:
    """Validate + parse + persist a manual. If `replace` is given, overwrite that
    document in place (so the sha/cache key self-invalidates); else create a new one.
    Callers should size-check the upload BEFORE materializing `data` (see kb_doc_upload)."""
    from django.core.files.base import ContentFile

    if not data or data[:5] != _PDF_MAGIC:
        raise IngestError("Not a PDF file (missing %PDF- header).")
    if len(data) > MAX_PDF_BYTES:
        raise IngestError(f"PDF too large ({len(data) // 1024 // 1024} MB > {MAX_PDF_BYTES // 1024 // 1024} MB).")

    text = parse_pdf_text(io.BytesIO(data))
    doc = replace or MachineDocument(machine=machine)
    doc.machine = machine
    doc.lang = lang
    doc.kind = kind
    doc.parsed_text = text
    doc.token_estimate = max(len(text) // 4, 0)  # ~4 chars/token heuristic
    doc.sha256 = hashlib.sha256(data).hexdigest()
    # A replaced manual is a different book: drop the alarm-code scan rather than let a
    # verdict about the OLD bytes govern what we tell customers about the new ones. Cleared
    # (not re-run) here so an upload never blocks on a model call — kb.alarms treats an
    # unscanned document as "unknown", i.e. today's behaviour, until scan_alarm_codes runs.
    doc.documents_alarm_codes = False
    doc.alarm_codes = []
    doc.alarm_scan_sha = ""
    old_name = replace.pdf.name if (replace and replace.pdf) else None
    doc.pdf.save(filename, ContentFile(data), save=True)
    # Replace-in-place: remove the superseded physical file (FileField.save doesn't).
    if old_name and old_name != doc.pdf.name:
        try:
            doc.pdf.storage.delete(old_name)
        except Exception:  # noqa: BLE001  (cleanup is best-effort; never break the upload)
            pass
    return doc
