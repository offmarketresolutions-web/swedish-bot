"""Trust-boundary helpers (V2 security S1/S3/S4/S8). The LLM is never a boundary —
these neutralize untrusted text before it enters prompts, slots, or lead sinks.

- wrap_untrusted(): Microsoft "spotlighting" — mark untrusted spans as DATA so the
  model treats them as content, never instructions.
- clean_*(): strict field validators for contact + identification values that flow
  into emails / WordPress / webhooks (prevents header/body injection) and into the
  deterministic trigram query (prevents identification poisoning).
"""
from __future__ import annotations

import re

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DELIM = re.compile(r"<<\s*/?\s*(?:UNTRUSTED|END_UNTRUSTED)[^>]*>>", re.IGNORECASE)
_OVERRIDE = re.compile(
    r"(?i)\b(ignore (all |any |the )?(previous|prior|above) (instructions|prompts?)"
    r"|system prompt|you are now|disregard (the|all))\b"
)


def strip_control(s: str) -> str:
    return _CTRL.sub("", s or "")


def no_crlf(s: str) -> str:
    return (s or "").replace("\r", " ").replace("\n", " ").strip()


def cap(s: str, n: int) -> str:
    return (s or "")[:n]


def wrap_untrusted(text: str, kind: str = "user_input") -> str:
    """Spotlight untrusted content as DATA. Strips our delimiter tokens + neutralizes
    obvious override markers so they can't break out of the envelope."""
    t = strip_control(text or "")
    t = _DELIM.sub("", t)
    t = _OVERRIDE.sub("[redacted]", t)
    return f'<<UNTRUSTED kind="{kind}">>\n{t}\n<<END_UNTRUSTED>>'


# ── strict field validators (return cleaned value, or "" when unusable) ──

_NAME_BAD = re.compile(r"[^\w .'\-]", re.UNICODE)
_PHONE_BAD = re.compile(r"[^0-9+\-() ]")
_MODEL = re.compile(r"^[A-Za-z0-9 ./\-]{1,40}$")
# A code SHAPE (must contain a digit), e.g. 'E11', 'H01 5252', 'Z1' — so a real code
# with a sub-group space is accepted, but free-text phrases ('ignore this') are not.
_ERRCODE = re.compile(r"^[A-Za-z]{0,4}\d[A-Za-z0-9]*(?:[ \-][A-Za-z0-9]{1,6})?$")
_POSTAL_BAD = re.compile(r"[^0-9 ]")


def clean_name(s: str) -> str:
    return _NAME_BAD.sub("", no_crlf(cap(s, 80)))


def clean_phone(s: str) -> str:
    """Normalize to E.164 ('+CCdigits'); '' if it isn't a plausible phone. A national
    number (leading 0) assumes Sweden (+46); '00' / '+' prefixes are kept as the country
    code; bare digits without a code are rejected as ambiguous.
    ponytail: regex E.164 shape-check, swap in `phonenumbers` if you need real per-country
    range validation (rejects e.g. +46 numbers that don't map to an assigned range)."""
    raw = re.sub(r"[^\d+]", "", no_crlf(cap(s, 32)))
    if raw.startswith("00"):
        num = "+" + raw[2:]
    elif raw.startswith("+"):
        num = "+" + raw[1:].replace("+", "")
    elif raw.startswith("0"):
        num = "+46" + raw.lstrip("0")
    else:
        num = ""  # bare digits with no country code → ambiguous, reject
    digits = num[1:]
    return num if num.startswith("+") and digits.isdigit() and 8 <= len(digits) <= 15 else ""


def clean_email(s: str) -> str:
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    s = no_crlf(cap(s, 200))
    try:
        validate_email(s)
        return s
    except ValidationError:
        pass
    # Django's validator is ASCII-only in the local part, so 'görel.svensson@email.com'
    # was rejected and re-asked (transcript review 2026-09-05, D016). Accept an
    # internationalized local part (RFC 6531) by shape — exactly one '@', no whitespace,
    # a dotted domain — and keep the address exactly as typed (never transliterate: the
    # customer's real mailbox is 'görel', not 'gorel').
    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", s) and s.count("@") == 1:
        return s
    return ""


def clean_postal(s: str) -> str:
    return _POSTAL_BAD.sub("", no_crlf(cap(s, 20)))[:10]


# A Swedish postcode is 5 digits, often written 'NNN NN'. Pull the first such group out
# of a free-text reply ('postnummer 852 34, Sundsvall' -> '85234'). Space-tolerant.
# Returns '' when no 5-digit group is present (full geocoding lands in S5).
_POSTCODE_SE = re.compile(r"(?<!\d)(\d{3})\s?(\d{2})(?!\d)")


def normalize_postcode(s: str) -> str:
    m = _POSTCODE_SE.search(no_crlf(cap(s, 40)))
    return (m.group(1) + m.group(2)) if m else ""


def clean_address(s: str) -> str:
    return strip_control(no_crlf(cap(s, 160)))


def clean_model(s: str) -> str:
    """Identification token (model/serial). Reject sentence-like content (a model is
    a short token like 'IVT 490' / 'Geo 600C', never a sentence/instruction)."""
    s = no_crlf(cap(s, 40))
    if not _MODEL.match(s) or len(s.split()) > 4:
        return ""
    return s


def clean_error_code(s: str) -> str:
    s = no_crlf(cap(s, 16))
    return s if _ERRCODE.match(s) else ""


# An alarm/fault code embedded in free text: a letter+digits token (E15, H01, F2),
# optionally followed by a sub-code group (H01 5252). Anchored to NOT match model
# names like "Geo 412C" (digit-first) or bare years.
_ERRCODE_IN_TEXT = re.compile(r"\b([A-Za-z]{1,3}\d{1,4}(?:[ \-]\d{2,5})?)\b")
_ALARM_CONTEXT = re.compile(r"(?i)\b(alarm|larm|error|fault|fel|kod|code|felkod|larmkod)\b")


def extract_error_code(text: str) -> str:
    """Best-effort pull of an alarm/fault code out of a free-text problem description
    (e.g. 'larm H01 5252 och ingen värme' -> 'H01 5252'). Only fires when the text
    actually mentions an alarm/error, so plain symptom text never yields a false code.
    Returns '' if none found."""
    s = text or ""
    if not _ALARM_CONTEXT.search(s):
        return ""
    m = _ERRCODE_IN_TEXT.search(s)
    return clean_error_code(m.group(1)) if m else ""


def clean_lead_field(s: str, n: int = 200) -> str:
    """For any user-sourced value bound for an email/webhook/WP form: no CR/LF, no
    control chars, length-capped (prevents header injection / oversized junk)."""
    return strip_control(no_crlf(cap(s, n)))
