"""Check real conversation transcripts against the owner's workflow specification.

The spec is docs/spec/owner-workflow-spec.md (the owner's own letter). The live-eval
judge grades OUTCOMES (did the case end in the right place); this checks CONFORMANCE
(did the conversation follow the rules the owner actually wrote). They catch different
things: a conversation can reach the right outcome while breaking several spec rules on
the way, and that is exactly what the owner would notice.

    python tools/eval/spec_conformance.py --file judged-run100.jsonl
    python tools/eval/spec_conformance.py --file results-cur.jsonl --rule S7-INSTALLER-MENU
    python tools/eval/spec_conformance.py --file results-cur.jsonl --violations

Every rule cites the spec section it comes from. Pure Python — no Django, no DB, no
network — so it is cheap enough to run on every eval batch.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "evals" / "2026-07-12-live-eval"

# ── helpers ──────────────────────────────────────────────────────────────────


def bot_turns(rec: dict) -> list[str]:
    return [m.get("content") or "" for m in (rec.get("transcript") or [])
            if m.get("role") == "assistant"]


def user_turns(rec: dict) -> list[str]:
    return [m.get("content") or "" for m in (rec.get("transcript") or [])
            if m.get("role") == "user"]


def turns(rec: dict) -> list[tuple[str, str]]:
    return [(m.get("role") or "", m.get("content") or "") for m in (rec.get("transcript") or [])]


def _any(patterns: list[str], text: str) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(0)
    return None


# The spec forbids INSTRUCTING the customer to do professional work; it explicitly ALLOWS
# warning them off it ("the refrigerant circuit must only be handled by authorized
# personnel") and safe observation ("look at the expansion vessel to see which type it is").
# Without this distinction a keyword scan flags the bot for doing exactly the right thing —
# it did, on 8/8 of the first run's hits.
_SV_VERB = r"(?:f[öo]rs[öo]k\w*|justera\w*|r[öo]r|hantera\w*|[öo]ppna\w*|[äa]ndra\w*|byt\w*|lyft\w*)"
_PROHIBITION = re.compile(
    # Swedish negates on BOTH sides of the verb: "inte röra" but also "rör eller hantera
    # inte enheten", which is the ordinary word order and the one the deterministic
    # refrigerant warning uses. Matching only the pre-verb form flagged that exact safety
    # message as if it were DIY advice.
    rf"(inte\s+{_SV_VERB}|{_SV_VERB}(?:\s+\w+){{0,3}}\s+inte\b|"
    r"f[åa]r inte|ska inte|b[öo]r inte|"
    r"undvik|aldrig|endast av|m[åa]ste (?:hanteras |utf[öo]ras )?av (?:beh[öo]rig|auktoriserad)|"
    r"beh[öo]rig (?:tekniker|personal)|auktoriserad|"
    r"do not|don'?t|never|must only be|should not|must not|only be (?:handled|done|performed) by|"
    r"authori[sz]ed|qualified (?:technician|personnel)|leave (?:this|that) to)", re.I)


_PROHIBITION_WINDOW = 200  # chars either side of the hit — see docstring below.


def _is_prohibition(text: str, at: int) -> bool:
    """True when the forbidden term sits inside a warning rather than an instruction.

    Checked in a WINDOW around the specific hit (`at`), not the whole turn. The window has
    to be generous: the deterministic refrigerant-emergency template names the hazard first
    and forbids touching it ~130 characters later ("...open windows to ventilate... and
    don't touch or operate the unit"), and a too-small window missed that and flagged the
    correct safety message on five safety conversations. But scanning the WHOLE turn went
    too far the other way: a generic closing disclaimer ("...ska alltid utföras av behörig
    personal") anywhere in a long turn silenced a real, unrelated instruction near the start
    of the very same turn — confirmed by test_a_far_away_generic_safety_footer_does_not_
    mask_an_unrelated_instruction. The window is the fix: wide enough for the refrigerant
    template's own gap, too narrow for an unrelated footer several sentences away.
    """
    lo, hi = max(0, at - _PROHIBITION_WINDOW), at + _PROHIBITION_WINDOW
    return bool(_PROHIBITION.search(text[lo:hi]))


def _instructed(patterns: list[str], text: str, *, needs_verb: bool = False) -> str | None:
    """Return the hit only when the bot is TELLING the customer to do it."""
    for p in patterns:
        for m in re.finditer(p, text, re.I):
            if _is_prohibition(text, m.start()):
                continue
            if needs_verb and not _action_on(m, text):
                continue
            return m.group(0)
    return None


# An action verb aimed at a professional-only COMPONENT. Naming a component is allowed and
# often required — "H01 5252 indicates a high-pressure alarm in the refrigerant circuit" is
# the manual's own alarm meaning (§6), and "look at the expansion vessel to see which type
# it is" is a safe observation (§10). Only WORK on the component is forbidden. Without this
# gate every such correct turn is flagged; it was 6/6 of the second run's remaining hits.
_ACTION_VERB = re.compile(
    r"\b(fyll|fylla|p[åa]fyllning|justera|st[äa]ll|[äa]ndra|[öo]ppna|byt|byta|demontera|"
    r"t[öo]m|t[öa]mma|koppla (?:ur|bort|f[öo]rbi)|skruva|lossa|montera|reparera|"
    r"fill|top up|adjust|set|change|replace|open|remove|drain|disconnect|unscrew|"
    r"dismantle|repair|service)\b", re.I)


def _action_on(term_match, text: str) -> bool:
    """True when an action verb sits close enough to be operating ON the component."""
    a, b = term_match.start(), term_match.end()
    return bool(_ACTION_VERB.search(text[max(0, a - 90):b + 90]))


# ── §7 / §8 / §10 — actions the spec forbids in customer-facing text ─────────
# The owner lists these explicitly as professional-only. The bot's own guardrails cover
# some; these are the ones named in the letter, in Swedish and English.
# COMPONENT_TERMS need an action verb nearby; ACTION_TERMS already denote the action.
COMPONENT_TERMS = {"refrigerant work", "expansion vessel work", "safety valve work",
                   "pressure-tank precharge", "anti-legionella", "changing filter media"}

FORBIDDEN_GUIDANCE = {
    "installer/service/factory menu": [
        r"installat[öo]rsmeny", r"servicemeny", r"fabriksinst[äa]llning",
        r"installer menu", r"service menu", r"factory setting",
    ],
    "pump speed": [r"pumphastighet", r"pump speed", r"varvtal p[åa] pumpen"],
    "compressor limit": [r"kompressorbegr[äa]nsning", r"compressor limit"],
    "sensor calibration": [r"givarkalibrering", r"kalibrera givare", r"sensor calibration"],
    "anti-legionella": [r"legionella"],
    "frost protection setting": [r"frysskydds?inst[äa]llning", r"frost protection setting"],
    "pressure switch adjustment": [
        r"justera\s+tryckvakt", r"st[äa]lla?\s+in\s+tryckvakt", r"adjust(?:ing)?\s+the\s+pressure switch",
        r"start[- ]och stopptryck", r"start/stop pressure",
    ],
    "pressure-tank precharge": [r"f[öo]rtryck", r"precharge", r"pre-charge"],
    "lifting a well pump": [
        # Both the definite ("pumpen") and indefinite ("en pump") forms — Swedish welds
        # the article onto the noun, so requiring "pumpen" alone let "lyfta upp en
        # brunnspump" through untouched.
        r"lyfta?\s+(?:upp\s+)?(?:en\s+)?(?:brunns)?pump(?:en)?\b",
        r"dra upp (?:en\s+)?(?:brunns)?pump(?:en)?\b",
        r"lift(?:ing)? (?:a|the) (?:well )?pump", r"pull(?:ing)? (?:a|the) (?:well )?pump",
    ],
    "opening a pump controller": [r"[öo]ppna\s+pumpstyrning", r"open(?:ing)? the pump controller"],
    "refrigerant work": [r"k[öo]ldmedi", r"refrigerant"],
    "expansion vessel work": [r"expansionsk[äa]rl", r"expansion vessel"],
    "safety valve work": [r"s[äa]kerhetsventil", r"safety valve"],
    "changing filter media": [
        # Mirrors chat/guardrails.py's own phrasing (byt\w* + fyll\w* på + ers[äa]tt\w*),
        # which already covers the imperative "byt" — this detector only had "byta".
        r"byt\w*\s+(?:ut\s+)?filtermass\w*",
        r"fyll\w*\s+p[åa]\s+filtermass\w*",
        r"ers[äa]tt\w*\s+(?:ut\s+)?filtermass\w*",
        r"change\s+(?:the\s+)?filter media",
    ],
    "increasing chemical dosing": [
        # "höj" as well as "öka", and the indefinite "dosering" as well as "doseringen".
        r"(?:[öo]ka|h[öo]j)\w*\s+doserin\w*",
        r"increase\s+(?:the\s+)?dosing",
    ],
    "bypassing a safety device": [r"f[öo]rbikoppla", r"bypass(?:ing)? (?:the )?(?:safety|protection)"],
}

# §7 — on a SUDDEN change the spec forbids "just raise the curve / hot-water setting".
# "öka" used to be bound only to (värme)kurvan, so "öka varmvattentemperaturen" escaped;
# "höj framledningstemperaturen" / "öka framledningen" / "skruva upp kurvan" were missing
# entirely — framledningstemperatur (flow temperature) is the other setting owners raise.
RAISE_SETTING = [
    r"h[öo]j(?:a|er)?\s+(?:v[äa]rmekurvan|kurvan|varmvattentemperaturen|temperaturen|framledning\w*)",
    r"[öo]ka\w*\s+(?:v[äa]rmekurvan|kurvan|varmvattentemperaturen|temperaturen|framledning\w*)",
    r"skruva\s+upp\s+(?:v[äa]rmekurvan|kurvan)",
    r"rais(?:e|ing)\s+(?:the\s+)?(?:heating curve|curve|hot[- ]water temperature|flow temperature)",
    r"increas(?:e|ing)\s+(?:the\s+)?(?:heating curve|curve|flow temperature|hot[- ]water temperature)",
]

# §2.9 — contact details must not be requested during TECHNICAL intake. The original three
# phrases were exact strings, not the range of ways to ask the same question ("Kan du ge
# mig ditt namn", "Vad är ditt telefonnummer").
CONTACT_ASK = [
    r"vad heter du", r"ge mig ditt namn", r"vad [äa]r ditt namn",
    r"vilket telefonnummer", r"vad [äa]r ditt telefonnummer", r"\bditt telefonnummer\b",
    r"din e-?post",
    r"what'?s your name", r"can you (?:give|tell) me your name", r"what is your name",
    r"best phone number", r"what'?s your phone number", r"your phone number",
    r"your email",
]

# §4 — a known manufacturer must survive routing, not be flattened to "other"/"unknown".
# The old 12-brand list missed common Swedish-market manufacturers entirely.
KNOWN_BRANDS = ["nibe", "ctc", "thermia", "grundfos", "callidus", "bosch", "ivt",
                "mitsubishi", "daikin", "panasonic", "debe", "aqua",
                "nilan", "j[äa]spi", "vaillant", "danfoss", "villavarme",
                "viessmann", "buderus", "wilo", "toshiba", "fujitsu",
                "calorex", "metro therm", "dab"]

# §9 — must not refer the customer elsewhere merely for being non-catalog. The customer
# saying "kontakta Nordland VVS" (or the bot offering to) is the CORRECT outcome — none of
# these patterns may ever match "nordland".
_REFER_BRANDS = "|".join(b for b in KNOWN_BRANDS)
REFER_AWAY = [
    rf"kontakta\w*\s+(?:din\s+)?(?:[åa]terf[öo]rs[äa]ljare|tillverkaren|leverant[öo]ren|"
    rf"installat[öo]r(?:en)?|{_REFER_BRANDS})\b",
    r"h[öo]r av dig till (?:serviceverkstaden|tillverkaren|[åa]terf[öo]rs[äa]ljaren|"
    r"din installat[öo]r(?:en)?)",
    r"contact\s+(?:your\s+)?(?:retailer|dealer|the manufacturer|supplier|installer)",
    r"v[äa]nd dig till tillverkaren",
]

RULES: list[dict] = []


def rule(rid, section, desc):
    def deco(fn):
        RULES.append({"id": rid, "section": section, "desc": desc, "fn": fn})
        return fn
    return deco


# ── rules ────────────────────────────────────────────────────────────────────

@rule("S7-FORBIDDEN-GUIDANCE", "§7/§8/§10",
      "Never guide the customer into professional-only work (installer menus, refrigerant, "
      "pressure switch, precharge, media change, bypassing safety devices...)")
def _forbidden(rec):
    out = []
    for text in bot_turns(rec):
        for label, pats in FORBIDDEN_GUIDANCE.items():
            hit = _instructed(pats, text, needs_verb=label in COMPONENT_TERMS)
            if hit:
                out.append(f"{label}: …{hit}…")
    return out


@rule("S7-SUDDEN-NOT-A-SETTING", "§7/§8",
      "On a SUDDEN change, do not simply raise the heating curve or hot-water setting")
def _sudden(rec):
    if (rec.get("slots") or {}).get("onset") != "sudden":
        return []
    return [f"sudden onset but told to raise a setting: …{hit}…"
            for text in bot_turns(rec) if (hit := _instructed(RAISE_SETTING, text))]


@rule("S2-NO-CONTACT-IN-INTAKE", "§2.9",
      "Do not ask for name/phone/email/address during technical intake — only after the "
      "answer has been given or service offered")
def _contact_timing(rec):
    seq = turns(rec)
    # Two legitimate openings for contact collection, and intake is everything before the
    # first of them: the technician handoff, and — after a self-solved case — the offer to
    # pass the details to a specialist. §2.9 forbids asking DURING technical intake; it
    # does not forbid asking once the customer already has their answer.
    offer = re.compile(r"tekniker fr[åa]n Nordland|Nordland VVS technician|"
                       r"skickar detta vidare|pass this to a Nordland|"
                       r"specialists? review|specialister? g[åa]r igenom|"
                       r"phone number and email|telefonnummer och din e-post", re.I)
    offered_at = next((i for i, (role, c) in enumerate(seq) if role == "assistant" and offer.search(c)), None)
    out = []
    for i, (role, c) in enumerate(seq):
        if role != "assistant":
            continue
        hit = _any(CONTACT_ASK, c)
        if hit and (offered_at is None or i < offered_at):
            out.append(f"asked for contact details at turn {i} before offering service: …{hit}…")
    return out


@rule("S2-POSTCODE-EARLY", "§2.10",
      "Ask for the postcode early, directly after the main category is known")
def _postcode_early(rec):
    slots = rec.get("slots") or {}
    # §2.10 is conditional on the main category being known. An off-domain close (the
    # customer never had in-scope equipment) never reaches that precondition, and asking
    # such a person for a postcode would itself be wrong.
    cat = (slots.get("category") or "").strip().lower()
    if cat in ("", "unknown") or rec.get("decision") == "off_domain_close":
        return []
    seq = [c for role, c in turns(rec) if role == "assistant"]
    pc = next((i for i, c in enumerate(seq)
               if re.search(r"postnummer|postal code", c, re.I)), None)
    if pc is None:
        return ["postcode never requested though the category was known"]
    # Greeting + category question, then the postcode. Later means a technical
    # questionnaire ran first, which the spec places after the postcode.
    return [] if pc <= 2 else [f"postcode first asked at bot turn {pc} (spec: directly after category)"]


@rule("S4-BRAND-PRESERVED", "§4",
      "A known manufacturer must survive routing — never flattened to other/unknown")
def _brand(rec):
    slots = rec.get("slots") or {}
    stated = " ".join(user_turns(rec)).lower()
    brand = (slots.get("brand") or "").strip().lower()
    for known in KNOWN_BRANDS:
        if re.search(rf"\b{known}\b", stated):
            if brand in ("", "other", "unknown", "okänd"):
                return [f"customer said '{known}' but slots.brand={slots.get('brand')!r}"]
            return []
    return []


@rule("S9-NO-REFER-AWAY", "§9",
      "Never refer the customer to the manufacturer/retailer merely because the equipment "
      "is not in the local catalog")
def _refer(rec):
    return [f"referred elsewhere: …{hit}…"
            for text in bot_turns(rec) if (hit := _instructed(REFER_AWAY, text))]


@rule("S3-MODEL-NOT-GUESSED", "§3",
      "A partial model must not be auto-resolved to one exact catalog machine")
def _model_guess(rec):
    slots = rec.get("slots") or {}
    model = (slots.get("model") or "").strip()
    # §2.8: "After two failed attempts, record the value as unknown" — the spec's own
    # instruction, so an unknown model is conformance, not a guess.
    if not model or model.lower() in ("unknown", "okänd", "vet inte"):
        return []
    said = re.sub(r"[\s\-_]", "", " ".join(user_turns(rec)).lower())
    # Token-wise, not contiguous: "CTC EcoHeat, jag tror det är en 8" legitimately yields
    # "EcoHeat 8". A guess is when a token appears that the customer never typed at all.
    invented = [tok for tok in re.findall(r"[A-Za-z0-9]+", model.lower())
                if tok not in said]
    return [f"confirmed model {model!r} contains {invented} never stated by the customer"] if invented else []


@rule("S13-FORM-NOT-A-BOOKING", "§11/§13",
      "The bot never books, schedules, dispatches or alerts — it offers to pass the case on")
def _form_claim(rec):
    """Two different wrongs, and the old rule could only see the rarer one.

    It matched past-tense confirmations ("bokningen är bekräftad") AND returned early
    whenever a ServiceRequest existed — so on 39 of 44 real conversations it checked
    nothing at all. But a lead is not a booking: "jag bokar in ett servicebesök" is false
    whether or not the case was sent, because the office schedules, not the bot. And the
    emergency line used to end "en tekniker larmas nu" with nothing dispatched at all.
    """
    # Wrong no matter what happened afterwards: the bot claiming it did the office's job.
    always = [
        r"jag (?:kommer att |ska |får |kan )?bokar? in",
        r"jag (?:har )?bokat",
        r"jag (?:kommer att |ska )?(?:skicka|lägga) (?:in )?en tekniker",
        r"i(?:'| a)?ll (?:book|schedule|line up|dispatch|send) (?:you )?a (?:tech|visit|service)",
        r"tekniker(?:n)? (?:är |kommer )?(?:på väg|imorgon|idag)",
        r"(?:en )?tekniker .{0,20}larmas",
        r"technician .{0,20}(?:is being alerted|has been alerted|is on (?:the|their) way)",
        r"bokning(?:en)? (?:är )?bekräftad",
        r"booking (?:is )?confirmed",
    ]
    # Wrong only when nothing was actually sent.
    only_without_lead = [r"din f[öo]rfr[åa]gan (?:är )?skickad.*formul[äa]r"]

    has_lead = bool((rec.get("artifacts") or {}).get("service_request_count"))
    patterns = always if has_lead else always + only_without_lead
    return [f"the bot claimed it books/dispatches: …{hit}…"
            for text in bot_turns(rec) if (hit := _any(patterns, text))]


@rule("S2-NO-INTERNAL-TAGS", "§2/§11",
      "Internal knowledge-citation tags ([K12]/[B3]/[W1 host]) must never appear in customer text")
def _tags(rec):
    return [f"internal tag shown to customer: {m}"
            for text in bot_turns(rec) for m in re.findall(r"\[(?:K|B|W)\d+[^\]]*\]", text)]


@rule("S2-NO-VERBATIM-REPEAT", "§2.4/§2.7",
      "Do not re-send an identical question; re-ask once then record unknown and move on")
def _repeat(rec):
    seen, out = {}, []
    for t in bot_turns(rec):
        k = t.strip()
        seen[k] = seen.get(k, 0) + 1
        if seen[k] == 3:  # asked the SAME thing three times = past the 2-attempt rule
            out.append(f"asked verbatim 3+ times: {k[:80]!r}")
    return out


@rule("S1-NO-REASKING-KNOWN-FACTS", "§1/§2.3",
      "Never ask again for a fact the customer already gave — measured by the customer "
      "having to say so ('I already told you', 'det sa jag ju')")
def _reask_known(rec):
    complain = re.compile(
        r"jag (?:har )?redan (?:sagt|f[öo]rklarat|n[äa]mnt|skrivit)|som jag (?:sa|sagt|n[äa]mnde)|"
        r"jag sa ju|det sa jag|i already (?:told|said|explained|mentioned)|that'?s what i said|"
        r"as i (?:said|told you)|i just told you|like i said", re.I)
    # An off-domain caller (refund demand, "write me a Python script", API keys) says
    # "I already told you" about their OFF-DOMAIN request; re-asking what equipment it is
    # is then correct, not a re-ask of a known technical fact.
    cat = ((rec.get("slots") or {}).get("category") or "").strip().lower()
    if cat in ("", "unknown") or rec.get("decision") == "off_domain_close":
        return []
    seq = turns(rec)
    out = []
    for i, (role, c) in enumerate(seq):
        if role == "user" and complain.search(c):
            asked = seq[i - 1][1][:80] if i else "(opening)"
            out.append(f"customer had to repeat themselves after: {asked!r}")
    return out


@rule("S7-ONSET-ESTABLISHED", "§7",
      "Establish always/gradual vs sudden before deciding a comfort or performance case — "
      "it is what decides between a documented user setting and offering service")
def _onset(rec):
    slots = rec.get("slots") or {}
    cat = (slots.get("category") or "").strip().lower()
    if cat in ("", "unknown"):
        return []
    comfort = re.compile(
        r"för kallt|för varmt|kallare|varmare|inte varmt|ljummet|svalare|varmvatt|"
        r"too cold|too warm|not heating|no heat|less hot water|lukewarm|colder|weaker", re.I)
    if not any(comfort.search(c) for c in user_turns(rec)):
        return []
    if slots.get("onset"):
        return []
    return ["comfort/performance complaint decided without establishing onset "
            "(always/gradual vs sudden)"]


@rule("S12-POSTCODE-NORMALISED", "§2/§12",
      "A captured postcode must be normalised to five digits — PostcodeArea is keyed on "
      "them, so an unnormalised value silently misses the service-area check")
def _postcode_normalised(rec):
    pc = (rec.get("slots") or {}).get("postal_code")
    if not pc or str(pc).lower() == "unknown":
        return []
    return ([] if re.fullmatch(r"\d{5}", str(pc))
            else [f"postcode {pc!r} was never normalised to five digits"])


@rule("S3-MODEL-IS-NOT-AN-ALARM", "§1/§3",
      "An alarm code is a fault reading, never the machine's model")
def _alarm_as_model(rec):
    model = ((rec.get("slots") or {}).get("model") or "").strip()
    if model and re.fullmatch(r"[A-Za-z]{1,3}\d{1,4}[ \-]\d{2,5}", model):
        return [f"alarm code {model!r} stored as the model"]
    return []


_SUMMARY_DISCLOSES = re.compile(
    r"\bmissing\b|\bsaknas\b|\bej\s+f[åa]ngat"
    r"|not (?:captured|provided|given|specified|mentioned|confirmed)"
    r"|were (?:not )?captured|no (?:specific )?(?:equipment|model|error code|felkod)"
    r"|ok[äa]nd|inte (?:angiv|f[åa]ngat|k[äa]nt)", re.I)


@rule("S11-SUMMARY-STATES-GAPS", "§11",
      "A lead summary must say when an important detail is missing (exact model, error "
      "code, contact, consent, booking) rather than reading as if the case were complete")
def _summary_gaps(rec):
    """§11 names five things the summary must disclose when absent. The old rule checked
    only the first (model) and — worse — returned early the moment the model WAS known, so
    a summary that hid a missing error code, missing contact details, missing consent, or
    an unconfirmed booking was never even looked at as long as the model happened to be
    captured.
    """
    slots = rec.get("slots") or {}
    artifacts = rec.get("artifacts") or {}
    contact = rec.get("contact") or {}

    model = (slots.get("model") or "").strip().lower()
    error_code = (artifacts.get("error_code") or "").strip().lower()

    gaps = []
    if not model or model == "unknown":
        gaps.append("exact model not captured")
    if not error_code or error_code == "unknown":
        gaps.append("no error code captured")
    if not (contact.get("phone") or contact.get("email")):
        gaps.append("contact details not captured")
    if not contact.get("consent"):
        gaps.append("consent not captured")
    # §13: nothing in this system confirms a booking — the office schedules after
    # receiving the lead — so this is always an open status the summary must report.
    gaps.append("booking not confirmed")

    out = []
    for sr in (artifacts.get("service_requests") or []):
        summary = (sr.get("payload_json") or {}).get("summary") or ""
        if summary and not _SUMMARY_DISCLOSES.search(summary):
            out.append(f"lead created but summary discloses none of: {', '.join(gaps)}")
    return out


# ── runner ───────────────────────────────────────────────────────────────────

def run(rows: list[dict], only: str | None = None) -> dict:
    results = {}
    for r in RULES:
        if only and r["id"] != only:
            continue
        violations = []
        for rec in rows:
            if rec.get("error"):
                continue
            for v in r["fn"](rec):
                violations.append((rec["id"], v))
        results[r["id"]] = {"rule": r, "violations": violations}
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="judged-run100.jsonl")
    ap.add_argument("--rule", default=None)
    ap.add_argument("--violations", action="store_true", help="list every violation")
    args = ap.parse_args()

    path = EVAL_DIR / args.file
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    graded = [r for r in rows if not r.get("error")]
    res = run(rows, args.rule)

    print(f"Spec conformance — {args.file} ({len(graded)} conversations graded)\n")
    print(f"{'RULE':28} {'SPEC':10} {'CONVS':>6}  STATUS")
    print("-" * 78)
    total_bad = 0
    for rid, r in res.items():
        bad = {cid for cid, _ in r["violations"]}
        total_bad += len(bad)
        status = "PASS" if not bad else f"FAIL  {len(r['violations'])} violations"
        print(f"{rid:28} {r['rule']['section']:10} {len(bad):>6}  {status}")
    print("-" * 78)
    clean = [r for r in graded
             if not any(r["id"] == cid for x in res.values() for cid, _ in x["violations"])]
    print(f"fully spec-conformant conversations: {len(clean)}/{len(graded)} "
          f"({100 * len(clean) // max(len(graded), 1)}%)")

    if args.violations:
        for rid, r in res.items():
            if not r["violations"]:
                continue
            print(f"\n### {rid} — {r['rule']['desc']}")
            for cid, v in r["violations"][:25]:
                print(f"  {cid}: {v}")
            if len(r["violations"]) > 25:
                print(f"  … {len(r['violations']) - 25} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
