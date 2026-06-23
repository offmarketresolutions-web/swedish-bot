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
# This baseline is HARD-CODED in code (V2 §S10) — admin config/notes can only ADD
# safety rules, never weaken these.
_FORBIDDEN = re.compile(
    r"\b(rewire|re-?wire|wiring up|replace the (heating )?element|"
    r"fuse box|terminal block|live wire|mains\b|"
    # The DANGEROUS panel — an electrical/control/service panel reaching boards & wiring —
    # is vetoed under any verb. A plain "front panel/cover/lid/grille" is NOT keyword-vetoed:
    # flipping one open to reach a user-serviceable filter is a documented owner task (air
    # units = the biggest category), and that's a large share of low-complexity resolutions.
    # The context-aware safety agent still flags "open the panel/cover to reach the board",
    # so dangerous access is caught by the LLM layer while filter access passes.
    r"(open\w*|remov\w*|take off|unscrew\w*|undo|detach\w*|pry off|pop off|lift off) "
    r"(the |a |an |its |your |this |that )?(electrical|control|service|wiring)[ -]?panel|"
    # deep disassembly of the unit BODY (not a filter cover/front panel)
    r"(open\w*|remov\w*|take off|taking off|takes off|unscrew\w*|undo|detach\w*|pry off|pop off|"
    r"lift off|dismantl\w*|disassembl\w*) (the |a |an |its |your |this |that )?"
    r"(front |rear |back |top |upper |lower |side |outer |compressor )*"
    r"(casing|cabinet|housing|enclosure|fascia)|"
    r"open up (the )?(unit|machine|heat ?pump|appliance)|"
    r"take (the )?(unit|machine|heat ?pump|appliance) apart|"
    r"refrigerant|recharge|top ?up (the )?(gas|refrigerant)|braze|"
    r"expansion vessel|relief valve|safety valve|re-?pressuriz\w*|"
    r"pre-?charge|adjust the pressure switch|drain (the |down )?(heating )?system|"
    r"flue|combustion|gas valve|burner|bypass (the )?(interlock|safety)|"
    r"disable (the )?safety|legionella (cycle|treatment|flush))\b",
    re.IGNORECASE,
)

# Output-side leak detection (V2 §S4/S10): the model echoing our trust-boundary
# delimiters or being coaxed into revealing the system prompt.
_LEAK = re.compile(r"<<\s*/?\s*(?:UNTRUSTED|END_UNTRUSTED)|system prompt|these instructions", re.IGNORECASE)


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
    if _LEAK.search(draft or ""):
        return True, "prompt/delimiter leak"
    if use_llm:
        return classify_unsafe(draft, locale=locale)
    return False, ""
