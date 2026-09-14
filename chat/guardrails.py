"""Code-level guardrail backstop (plan §6.4) — a prompt is not a security
boundary. A deterministic keyword veto + a cheap LLM safety classifier check
every delivered specialist draft for forbidden instruction classes.
"""
from __future__ import annotations

import json
import re

from chat import prompts
from core.services import gemini

# Forbidden INSTRUCTIONS: phrasings that ARE an instruction to perform pro/licensed work
# (a verb + the regulated target, or an inherently-instructional verb). Vetoed
# unconditionally. Tuned to catch instruction phrasing, not mere mention ("the wiring is
# fine" is OK; "rewire" not). HARD-CODED baseline (V2 §S10) — admin config can only ADD.
_FORBIDDEN_INSTRUCTION = re.compile(
    r"\b(rewire|re-?wire|wiring up|replace the (heating )?element|"
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
    # bare deep component (no casing-noun needed): "open/unscrew the compressor"
    r"(open\w*|remov\w*|take off|unscrew\w*|undo|detach\w*|pry off|pop off|lift off|"
    r"dismantl\w*|disassembl\w*) (the |a |an |its |your |this |that )?compressor\b|"
    r"recharge|top ?up (the )?(gas|refrigerant)|braze|re-?pressuriz\w*|"
    r"adjust the pressure switch|drain (the |down )?(heating )?system|"
    r"bypass (the )?(interlock|safety)|disable (the )?safety|legionella (cycle|treatment|flush)|"
    # Pure electrical / combustion / gas danger — regulated even to name to a customer, so
    # these stay ALWAYS-veto (unlike the refrigerant/pressure NOUNS below, which are exempt
    # on bare mention). Restores the pre-split baseline for this life-safety subset.
    r"fuse box|terminal block|live wire|mains\b|flue|combustion|gas valve|burner|"
    r"elskåp\w*|kopplingsplint\w*|strömförande|gasventil\w*|brännar\w*|rökgas\w*|"
    # Swedish aliases — sv is the primary locale, so the deterministic veto must not
    # be English-only. Same tuning: instruction-class terms, not mere mention.
    r"fyll(a|er)? på (gas\w*|köldmedi\w*)|löd(a|er|ning)\b|"
    r"koppla förbi|inaktivera säkerhet\w*|"
    r"(öppna|demonter\w*|ta isär|skruva (upp|loss|isär)) (den |en |ett |din |er )?"
    r"(enhet\w*|maskin\w*|värmepump\w*|aggregat\w*|kompressor\w*)|"
    r"töm(ma|mer)? (ner |ur )?(system\w*|köldmedi\w*|anläggning\w*)|tappa ur system\w*|"
    # ── S4 water pump / well / filtration professional tasks (instruction-class, en+sv) ──
    # Pressure switch / pressostat adjustment.
    r"adjust\w* (the )?(pressure switch|pressostat)|"
    r"(justera\w*|st[äa]ll\w* om|[äa]ndra\w*) (på )?(pressostat\w*|tryckvakt\w*)|"
    # Pulling / lifting a well pump.
    r"(pull\w*|lift\w*|rais\w*|draw\w*|hoist\w*|haul\w*|winch\w*) (up |out )?(the |your |a )?"
    r"(well ?pump|borehole pump|deep-?well pump|submersible pump)|"
    r"(dra|lyft|hiss\w*|ta) upp (den |er |din )?(brunnspump\w*|dränkbar\w* pump\w*)|"
    # Opening pump controllers / hydrofor / pressure tanks.
    r"(open\w*|remov\w*|dismantl\w*|disassembl\w*|take apart) (the |your |a )?"
    r"(pump controller|hydrofor\w*|pressure tank|pressure vessel)|"
    r"(öppna\w*|demonter\w*|ta isär) (den |er |ett )?(hydrofor\w*|tryckkärl\w*|trycktank\w*|pumpstyrning\w*)|"
    # Setting / adjusting tank precharge (förtryck).
    r"(set|adjust\w*|chang\w*|charg\w*|top ?up|increas\w*|reduc\w*) (the )?pre-?charge|"
    r"(st[äa]ll\w* in|justera\w*|[äa]ndra\w*|fyll\w* på) (förtryck\w*)|"
    # Replacing / refilling filter media (filtermassa).
    r"(replac\w*|chang\w*|refill\w*|renew\w*|top ?up|swap\w*) (the )?filter (media|medium|sand|mass)|"
    r"(byt\w*|fyll\w* på|ers[äa]tt\w*) (ut )?filtermass\w*|"
    # Adjusting the chemical dosing pump.
    r"(adjust\w*|set|chang\w*|increas\w*|reduc\w*|tun\w*) (the )?dos(e|ing|ing pump)|"
    r"(justera\w*|[äa]ndra\w*|st[äa]ll\w* in) (på )?(doseringen|dosering\w*|doseringspump\w*)|"
    # Bypassing dry-run / motor protection.
    r"(bypass\w*|disabl\w*|overrid\w*|jump\w* out|defeat\w*) (the )?(dry-?run|torrkörning\w*|motor|overload) "
    r"(protection|cut-?out|skydd)|"
    r"(koppla förbi|inaktivera\w*|förbikoppl\w*) (torrkörningsskydd\w*|motorskydd\w*)|"
    # Entering an installer / service menu.
    r"(enter\w*|go into|access\w*|unlock\w*) (the )?(installer|service|engineer) (menu|mode)|"
    r"(g[åa]\w* in i|öppna\w*|l[åa]s\w* upp|aktivera\w*) (installat[öo]rsmeny\w*|serviceläge\w*|servicemeny\w*)|"
    r"installat[öo]rsmeny\w*|serviceläge\b)\b",
    re.IGNORECASE,
)

# Regulated-domain NOUNS. Naming one is fine ("the refrigerant circuit is sealed — that's
# technician-only work" must survive); it only trips the veto when a MANIPULATION cue sits
# next to it (i.e. the draft is telling the customer to touch/open/alter it). Bare mentions
# fall through to the context-aware LLM classifier, so a specialist's safe explanation is no
# longer suppressed into a zero-content escalation (gap #4). Instruction phrasings above
# still veto unconditionally.
_FORBIDDEN_NOUN = re.compile(
    # Every Swedish noun here carries \w* so the DEFINITE form matches. Seven of them did
    # not, and the definite is how Swedes actually write: "öppna tryckvakten", not "öppna
    # tryckvakt". The veto saw the first and missed the second — the same word-boundary
    # assumption that let "köldmedieläckage" walk past the refrigerant emergency trigger.
    r"\b(refrigerant|pre-?charge|expansion vessel|relief valve|safety valve|pressure switch|"
    # S4 water-domain regulated nouns — mention-safe, veto only with a manipulation cue nearby.
    r"pressostat\w*|tryckvakt\w*|förtryck\w*|hydrofor\w*|tryckkärl\w*|filtermassa\w*|"
    r"filter media|doseringspump\w*|"
    r"brunnspump\w*|torrkörningsskydd\w*|dry-?run protection|"
    r"köldmedi\w*|kylkrets\w*|expansionskärl\w*|säkerhetsventil\w*)\b",
    re.IGNORECASE,
)

# Manipulation cues — verbs that turn a noun-mention into an instruction to DO the work.
# Look-only words (check, look, read, note, observe, confirm, switch off at the main) are
# deliberately absent: observing is always safe.
_MANIP_CUE = re.compile(
    r"\b(open\w*|remov\w*|take off|taking off|unscrew\w*|undo|detach\w*|pry|pop|lift off|"
    r"dismantl\w*|disassembl\w*|replac\w*|swap|recharg\w*|refill\w*|top ?up|fill\w*|add\b|"
    r"drain\w*|empt\w*|bleed|vent\w*|release|adjust\w*|loosen\w*|tighten\w*|disconnect\w*|"
    r"reconnect\w*|connect\w*|rewire|wir\w*|braz\w*|solder\w*|bypass\w*|disabl\w*|"
    r"pressuriz\w*|touch\w*|handl\w*|measur\w*|mess with|work on|get into|access\w*|tamper\w*|"
    r"crack\b|öppna\w*|ta bort|ta isär|skruva\w*|demonter\w*|byt\w*|fyll\w*|töm\w*|tappa\w*|"
    r"lossa\w*|koppla\w*|löd\w*|mät\w*|rör(a|er)?|pilla\w*|meka\w*|släpp\w*)\b",
    re.IGNORECASE,
)
_NOUN_CUE_WINDOW = 45  # chars each side of a noun to look for a manipulation cue

# Output-side leak detection (V2 §S4/S10): the model echoing our trust-boundary
# delimiters or being coaxed into revealing the system prompt.
_LEAK = re.compile(r"<<\s*/?\s*(?:UNTRUSTED|END_UNTRUSTED)|system prompt|these instructions", re.IGNORECASE)


def keyword_unsafe(text: str) -> tuple[bool, str]:
    t = text or ""
    m = _FORBIDDEN_INSTRUCTION.search(t)
    if m:
        return True, m.group(0)
    # A regulated-domain noun only vetoes when a manipulation cue sits near it (instruction),
    # not on bare mention (safe explanation → let the LLM layer judge).
    for nm in _FORBIDDEN_NOUN.finditer(t):
        lo, hi = max(0, nm.start() - _NOUN_CUE_WINDOW), min(len(t), nm.end() + _NOUN_CUE_WINDOW)
        if _MANIP_CUE.search(t[lo:hi]):
            return True, nm.group(0)
    return False, ""


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
