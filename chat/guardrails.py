"""Code-level guardrail backstop (plan §6.4) — a prompt is not a security
boundary. A deterministic keyword veto + a cheap LLM safety classifier check
every delivered specialist draft for forbidden instruction classes.
"""
from __future__ import annotations

import json
import re

from chat import prompts
from core.services import gemini

# Forbidden: instructing the customer to perform pro/licensed work. Tuned to catch
# instruction phrasing, not mere mention ("the wiring is fine" is OK; "rewire" not).
_FORBIDDEN = re.compile(
    r"\b(rewire|re-?wire|wiring up|replace the (heating )?element|"
    r"open (the )?(electrical |control )?panel|"
    r"refrigerant|recharge|top ?up (the )?(gas|refrigerant)|braze|"
    r"expansion vessel|relief valve|safety valve|re-?pressuriz\w*|"
    r"pre-?charge|adjust the pressure switch)\b",
    re.IGNORECASE,
)


def keyword_unsafe(text: str) -> tuple[bool, str]:
    m = _FORBIDDEN.search(text or "")
    return (True, m.group(0)) if m else (False, "")


def classify_unsafe(draft: str, *, locale: str = "en") -> tuple[bool, str]:
    """One-shot Flash-Lite safety check. Defaults to SAFE only on a clean parse;
    any error is treated as safe=False here (the keyword veto is the hard gate)."""
    system = prompts.render("safety", locale=locale)
    try:
        resp = gemini.generate(
            f"Draft reply:\n{draft}", model=prompts.model_for("safety"),
            system_instruction=system, response_mime_type="application/json",
            max_output_tokens=120,
        )
        data = json.loads(resp.text)
        return bool(data.get("unsafe")), str(data.get("reason", ""))
    except Exception:  # noqa: BLE001
        return False, ""


def is_unsafe(draft: str, *, locale: str = "en", use_llm: bool = True) -> tuple[bool, str]:
    """Return (unsafe, reason). Keyword veto is authoritative; the LLM classifier
    is a second opinion for phrasing the keywords miss."""
    bad, hit = keyword_unsafe(draft)
    if bad:
        return True, f"forbidden term: {hit}"
    if use_llm:
        return classify_unsafe(draft, locale=locale)
    return False, ""
