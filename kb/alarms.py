"""Does a manual actually document alarm/error codes?

The intake flow asks every customer to read the code off the display, and the
specialist is then asked what it means. When the loaded manual contains no code
table at all, the honest answer is "I can't tell you" — but a language model
holding 6 MB of heat-pump manual will happily produce a plausible meaning
instead. Measured on the live site: the IVT AirX 500 manuals define NO codes,
and the specialist answered "E4 indikerar ett fel med flödesgivaren" on one run
and "E4 betyder fel på extern värmekälla" on another. Two different fabrications,
same code, both stated to a homeowner as fact.

Prose cannot fix that — the specialist prompt already says "Never invent
error-code meanings" and it happened anyway. So we establish the fact ONCE, out
of band: one vision pass per manual (codes live in screenshots and display
photos, so the pdfplumber text layer misses them — "E4" appears zero times in
the AirX 500 text), recorded against the file's sha256 so it re-runs when the
manual is replaced.

Deliberately coarse. We only answer "does this manual document codes AT ALL",
not "is code X in it": some manuals list families ("Ex", "Px", "Fx") rather than
each code, so exact membership would refuse real codes. The coarse signal is the
one that is never ambiguous, and it covers the case where fabrication is
guaranteed rather than merely possible.
"""
from __future__ import annotations

import json
import logging

from core.constants import MODELS
from core.services import gemini

logger = logging.getLogger(__name__)

_SCAN_PROMPT = (
    "Does this appliance manual document the meaning of alarm, error or fault CODES — "
    "a table, list or section that maps a code to what it means? Look at screenshots, "
    "display photos and diagrams too, not only typeset tables.\n"
    "Answer with JSON only: {\"documents_codes\": true|false, \"codes\": [\"...\"]}\n"
    "codes: every code or code family you can actually see, verbatim (e.g. \"E4\", \"EH 02\", "
    "\"Ex\"). Empty list if none. Do NOT include codes you know from other products — only "
    "what is printed in THIS manual."
)


def _looks_like_a_code(token: str) -> bool:
    """Reject the placeholders a manual prints where a code would go.

    The AirX 500 scan came back with "xxxx" — the manual's own stand-in for "some
    number here". Taking that as a documented code would have flipped the verdict on
    the exact machine we caught fabricating "E4", so the filter matters more than its
    size suggests. Real codes seen across the catalog: E4, EH 02, FP, CL, Ex, A11 1010,
    E21.RHP, MB1, GT6, 5057.
    """
    t = token.strip()
    if not (2 <= len(t) <= 16):
        return False
    if len(set(t.lower().replace(" ", ""))) < 2:  # xxxx, ----, 000
        return False
    return any(ch.isalnum() for ch in t)


def scan_document(doc) -> tuple[bool, list[str]]:
    """One vision pass over `doc`. Returns (documents_codes, codes)."""
    if not doc.pdf:
        return False, []
    resp = gemini.generate(
        [gemini.file_part(doc.pdf.path), _SCAN_PROMPT],
        model=MODELS["flash"], response_mime_type="application/json",
        max_output_tokens=800, temperature=0.0,
    )
    raw = (getattr(resp, "text", "") or "").strip()
    data = json.loads(raw)
    codes = [str(c).strip() for c in (data.get("codes") or []) if _looks_like_a_code(str(c))]
    # Trust the list over the flag: a manual that named codes documents codes, whatever
    # the boolean says, and a "true" with nothing to show is not something to rely on.
    return (bool(data.get("documents_codes")) and bool(codes)) or bool(codes), codes[:200]


def scan_and_save(doc) -> tuple[bool, list[str]]:
    documents_codes, codes = scan_document(doc)
    doc.alarm_codes = codes
    doc.documents_alarm_codes = documents_codes
    doc.alarm_scan_sha = doc.sha256 or ""
    doc.save(update_fields=["alarm_codes", "documents_alarm_codes", "alarm_scan_sha"])
    return documents_codes, codes


def machine_documents_codes(machine) -> bool | None:
    """True  — at least one loaded manual documents alarm codes.
    False — every loaded manual was scanned against its current bytes and none does.
    None  — we don't know: no manuals, or one is unscanned/stale, so don't act on it.

    None and True behave identically at the call site (answer normally); only False
    is allowed to change what the customer is told, so an un-run scan can never make
    the bot refuse something it could have answered.
    """
    if machine is None:
        return None
    docs = [d for d in machine.documents.all() if d.pdf]
    if not docs:
        return None
    for d in docs:
        if not d.alarm_scan_sha or d.alarm_scan_sha != (d.sha256 or ""):
            return None  # stale or never scanned
        if d.documents_alarm_codes:
            return True
    return False
