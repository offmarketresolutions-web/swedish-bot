"""The orchestrator FSM (plan §6). Deterministic in code: counts turns, owns
CaseState, routes to exactly one agent per turn, runs the guardrail backstop,
flushes structured facts to crm.Session. The LLM never controls the flow.
"""
from __future__ import annotations

import json
import re

from django.conf import settings

from chat import context, guardrails, intake, prompts, sanitize
from chat.casestate import (
    flush_to_session,
    is_routable,
    new_case_state,
    next_required_slot,
)
from chat.i18n import t
from chat.intake import extract_answer
from chat.models import Conversation, Message
from core.enums import (
    STATE_ESCALATE,
    STATE_INTAKE,
    STATE_RESOLVED,
    STATE_ROUTING,
    STATE_SPECIALIST,
    STATE_UNSUPPORTED,
)
from core.services import gemini
from kb.identification import identify_machine

CONFIDENCE_GATE = 0.80
REPLY_BUDGET = 5
_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)
_NEG = re.compile(r"\b(not|don'?t|do not|never|inte|nej|no)\b", re.IGNORECASE)
_AFFIRM = re.compile(r"\b(yes|ja|sure|ok|okay|send it|please send|go ahead|do it|skicka|absolutely)\b",
                     re.IGNORECASE)


def _parse_json(text: str) -> dict:
    raw = _FENCE.sub("", text or "").strip()
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    # Salvage: parse the outermost {...} block (handles prose/fenced wrapping that
    # slips through when response_mime_type is weakened by cached_content).
    i, j = raw.find("{"), raw.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(raw[i:j + 1])
        except Exception:  # noqa: BLE001
            return {}
    return {}


# ── public API ────────────────────────────────────────────────────────

def open_conversation(language: str = "en") -> tuple[Conversation, dict]:
    conv = Conversation.objects.create(language=language, case_state=new_case_state())
    cs = conv.case_state
    cs["current_slot"] = "category"
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    return conv, {
        "message": t(language, "greeting") + " " + t(language, "q_category"),
        "chips": intake.chips_for("category", cs, language),
        "state": STATE_INTAKE,
    }


def process_turn(conversation: Conversation, user_text: str = "", image=None) -> dict:
    locale = conversation.language
    cs = conversation.case_state or new_case_state()
    if cs.get("turns", 0) >= getattr(settings, "MAX_TOTAL_TURNS", 25):  # S7 hard ceiling
        return {"message": t(locale, "terminal"), "chips": [],
                "state": cs.get("state", STATE_RESOLVED), "events": []}
    Message.objects.create(conversation=conversation, role="user", content=user_text or "", image=image)

    events: list[dict] = []
    if image:
        _run_vision(conversation, cs, events, locale)

    result = _advance(conversation, cs, user_text, events, locale)

    cs["turns"] = cs.get("turns", 0) + 1
    conversation.case_state = cs
    conversation.save(update_fields=["case_state", "updated_at"])
    Message.objects.create(
        conversation=conversation, role="assistant", content=result["message"],
        confidence=cs.get("confidence") or None, model=result.get("model", ""),
    )
    session = flush_to_session(conversation, cs)
    session.reply_turns = cs["turns"]
    if cs["state"] == STATE_ESCALATE:
        session.status = "escalated"
    session.save(update_fields=["reply_turns", "status"])

    result["state"] = cs["state"]
    result.setdefault("events", events)
    return result


# ── state handlers ─────────────────────────────────────────────────────

def _advance(conversation, cs, user_text, events, locale) -> dict:
    for _ in range(5):
        st = cs["state"]
        if st == STATE_INTAKE:
            out = _intake_step(cs, user_text, locale)
            if out is not None:
                return out
            user_text = ""  # consumed; fall through to routing
        elif st == STATE_ROUTING:
            _route(conversation, cs, events, locale)
        elif st == STATE_SPECIALIST:
            return _specialist_step(conversation, cs, events, locale)
        elif st == STATE_UNSUPPORTED:
            return _unsupported_step(conversation, cs, events, locale)
        elif st == STATE_ESCALATE:
            return _escalate_step(conversation, cs, user_text, locale)
        else:  # RESOLVED
            return _terminal_step(cs, locale)
    return {"message": _handoff_line(locale), "chips": _escalation_chips(locale)}


def _intake_step(cs, user_text, locale) -> dict | None:
    current = cs.get("current_slot")
    if current and user_text:
        on_target, value = extract_answer(current, user_text, cs, locale)
        if on_target and value:
            cs["slots"][current] = value
            cs["reask"] = 0
        else:
            cs["reask"] = cs.get("reask", 0) + 1
            if cs["reask"] >= 2:
                cs["slots"][current] = "unknown"
                cs["reask"] = 0
            else:
                return {"message": t(locale, "reask") + t(locale, "q_" + current),
                        "chips": intake.chips_for(current, cs, locale)}
    if is_routable(cs):
        cs["state"] = STATE_ROUTING
        return None
    nxt = next_required_slot(cs)
    if nxt is None:
        cs["state"] = STATE_ROUTING
        return None
    cs["current_slot"] = nxt
    return {"message": t(locale, "q_" + nxt), "chips": intake.chips_for(nxt, cs, locale)}


def _route(conversation, cs, events, locale):
    from kb.models import Category, ProblemCategory

    s = cs["slots"]
    query = sanitize.cap(
        " ".join(x for x in [s.get("brand"), s.get("model"), s.get("ocr_text")] if x and x != "unknown"), 120)
    machine, score = identify_machine(query)
    cs["match_confidence"] = score

    data = _call_router(cs, machine, locale)
    cs["severity"] = data.get("severity") or "normal"

    pc = None
    cat = Category.objects.filter(slug=s.get("category")).first()
    if cat and data.get("problem_category"):
        pc = ProblemCategory.objects.filter(category=cat, slug=data["problem_category"]).first()
    cs["problem_category_id"] = pc.id if pc else None

    events.append({"type": "tool_result", "name": "identify",
                   "result": {"machine": str(machine) if machine else None, "score": round(score, 3)}})

    if machine:
        cs["machine_id"] = machine.id
        cs["state"] = STATE_SPECIALIST
    else:
        cs["state"] = STATE_UNSUPPORTED
    flush_to_session(conversation, cs, machine=machine, problem_category=pc)


def _call_router(cs, machine, locale) -> dict:
    from kb.models import Machine

    catalog = ", ".join(str(m) for m in Machine.objects.filter(is_supported=True)[:50])
    system = prompts.render(
        "router", locale=locale,
        equipment=sanitize.wrap_untrusted(json.dumps(cs["slots"]), "facts"),
        problem=sanitize.wrap_untrusted(cs["slots"].get("problem", ""), "problem"),
        ocr_text=sanitize.wrap_untrusted(cs["slots"].get("ocr_text") or "", "ocr"),
        match=str(machine) if machine else "none", catalog_summary=catalog,
        problem_categories="", category=cs["slots"].get("category", ""),
    )
    try:
        resp = gemini.generate("Classify this case.", model=prompts.model_for("router"),
                               system_instruction=system, response_mime_type="application/json",
                               max_output_tokens=200)
        return _parse_json(resp.text)
    except Exception:  # noqa: BLE001
        return {}


def _specialist_step(conversation, cs, events, locale) -> dict:
    from kb.models import Machine

    machine = Machine.objects.get(id=cs["machine_id"])
    forced = cs.get("turns", 0) >= REPLY_BUDGET - 1
    brand_notes, faq = context.collect_knowledge(machine, locale)
    cached, inline = context.machine_pdf_context(machine, locale)

    system = prompts.render(
        "specialist", locale=locale, brand=machine.vendor.name, model=machine.model_name,
        category=machine.category.slug, brand_notes=brand_notes, faq=faq,
        problem=cs["slots"].get("problem", ""), symptoms="", error_code=cs["slots"].get("error_code") or "",
        serial=cs["slots"].get("serial") or "", forced_wrapup=str(forced).lower(),
    )
    turn = ("Customer problem: " + sanitize.wrap_untrusted(cs["slots"].get("problem", ""), "problem")
            + f"\nError code: {sanitize.clean_error_code(cs['slots'].get('error_code') or '') or 'none'}.")
    if cached:
        # Vertex forbids system_instruction alongside cached_content — inline the
        # (small, editable) instruction as a content part; only the PDFs are cached
        # (keeps prompt/notes edits effective immediately; resolves crit 0.4).
        resp = gemini.generate([system, turn], model=prompts.model_for("specialist"),
                               cached_content=cached, response_mime_type="application/json",
                               max_output_tokens=700)
    else:
        resp = gemini.generate([turn] + inline, model=prompts.model_for("specialist"),
                               system_instruction=system, response_mime_type="application/json",
                               max_output_tokens=700)
    data = _parse_json(resp.text)

    answer = data.get("answer_to_customer", "") or ""
    # S9: validate model output schema; anything off -> fail-closed to escalate.
    _c = data.get("confidence")
    conf = _c if isinstance(_c, (int, float)) and 0.0 <= _c <= 1.0 else 0.0
    if cs.get("match_confidence", 0) < 0.6:
        conf = min(conf, 0.5)
    if data.get("in_docs") is False:
        conf = min(conf, 0.6)
    cs["confidence"] = conf
    cs["decision"] = data["decision"] if data.get("decision") in ("solve", "escalate") else "escalate"
    cs["severity"] = (data["severity"] if data.get("severity") in ("urgent", "normal", "service")
                      else (cs.get("severity") or "normal"))
    cs["report"].update({k: v for k, v in (data.get("report") or {}).items() if v is not None})

    unsafe, reason = guardrails.is_unsafe(answer, locale=locale)
    if unsafe or conf < CONFIDENCE_GATE or cs["decision"] != "solve" or forced:
        cs["state"] = STATE_ESCALATE
        cs["decision"] = "escalate"
        cs["report"]["service_recommended"] = True
        cs["escalation_reason"] = (reason if unsafe else "") or (
            "low_confidence" if conf < CONFIDENCE_GATE else ("budget" if forced else "decision"))
        events.append({"type": "escalate", "reason": cs["escalation_reason"]})
        prefix = (answer + "\n\n") if (answer and not unsafe) else ""
        return _begin_escalation(cs, locale, prefix)

    cs["report"]["resolved"] = data.get("report", {}).get("resolved", True)
    return {"message": answer, "chips": [], "decision": "solve",
            "model": prompts.model_for("specialist")}


def _unsupported_step(conversation, cs, events, locale) -> dict:
    s = cs["slots"]
    system = prompts.render("intelligent_intake", locale=locale,
                            brand=s.get("brand") or "unknown", model=s.get("model") or "unknown",
                            category=s.get("category") or "unknown")
    try:
        resp = gemini.generate(f"Problem: {s.get('problem','')}", model=prompts.model_for("intelligent_intake"),
                               system_instruction=system, response_mime_type="application/json",
                               max_output_tokens=400)
        data = _parse_json(resp.text)
    except Exception:  # noqa: BLE001
        data = {}
    cs["state"] = STATE_ESCALATE
    cs["decision"] = "escalate"
    cs["severity"] = data.get("severity") or cs.get("severity") or "normal"
    cs["report"]["service_recommended"] = True
    cs["escalation_reason"] = "unsupported"
    answer = data.get("answer_to_customer") or ""
    events.append({"type": "escalate", "reason": "unsupported"})
    return _begin_escalation(cs, locale, (answer + "\n\n") if answer else "")


# ── escalation: lazy contact collection → approval → lead dispatch (Phase 6) ──

def _begin_escalation(cs, locale, prefix: str = "") -> dict:
    cs["contact_slot"] = "name"
    return {"message": prefix + t(locale, "escalate_leadin"), "chips": [], "decision": "escalate"}


def _next_contact_slot(cs) -> str | None:
    from chat.casestate import CONTACT_SLOTS

    for s in CONTACT_SLOTS:
        if cs["contact"].get(s) is None:
            return s
    return None


def _is_yes(text: str) -> bool:
    """S2: affirmative consent that's safe AND usable. The chip value 'yes_send',
    or an affirmative word with NO negation. 'yes please don't send' (negation) →
    False; 'yes, send it please' → True; 'not yet' → False."""
    txt = (text or "").strip().lower()
    if txt == "yes_send":
        return True
    if _NEG.search(txt):
        return False
    return bool(_AFFIRM.search(txt))


def _sync_customer(session, cs):
    from crm.models import Customer

    c = session.customer or Customer()
    ct = cs["contact"]
    c.name = ct.get("name") or c.name
    c.phone = ct.get("phone") or c.phone
    c.email = ct.get("email") or c.email
    c.postal_code = ct.get("postal_code") or c.postal_code
    c.consent_to_contact = bool(ct.get("consent"))
    c.save()
    session.customer = c
    session.save(update_fields=["customer"])


def _escalate_step(conversation, cs, user_text, locale) -> dict:
    if cs.get("awaiting_approval"):
        if _is_yes(user_text):
            from chat.casestate import flush_to_session
            from crm import leads

            session = flush_to_session(conversation, cs)
            _sync_customer(session, cs)
            session.booking_requested = True
            session.status = "escalated"
            session.save(update_fields=["booking_requested", "status"])
            leads.create_and_dispatch(session, cs.get("escalation_reason", ""))
            cs["state"] = STATE_RESOLVED
            name = cs["contact"].get("name") or ""
            phone = cs["contact"].get("phone") or ""
            name_sfx = (" " + name) if name else ""
            phone_sfx = (" " + t(locale, "phone_connector") + " " + phone) if phone else ""
            return {"message": t(locale, "thanks", name_sfx=name_sfx, phone_sfx=phone_sfx),
                    "chips": [], "decision": "escalate"}
        cs["state"] = STATE_RESOLVED
        return {"message": t(locale, "not_yet"), "chips": []}

    cur = cs.get("contact_slot")
    if cur and user_text:
        raw = (user_text or "").strip()
        if raw.lower() in ("skip", "none", "no") and cur == "email":
            val = ""
        else:  # S1: validate/sanitize each contact field at capture
            cleaner = {"name": sanitize.clean_name, "phone": sanitize.clean_phone,
                       "email": sanitize.clean_email, "postal_code": sanitize.clean_postal}.get(
                cur, sanitize.clean_lead_field)
            val = cleaner(raw)
        cs["contact"][cur] = val

    nxt = _next_contact_slot(cs)
    if nxt:
        cs["contact_slot"] = nxt
        return {"message": t(locale, "contact_" + nxt), "chips": [], "decision": "escalate"}

    cs["contact_slot"] = None
    cs["awaiting_approval"] = True
    cs["contact"]["consent"] = True
    return {"message": t(locale, "approval"), "chips": _escalation_chips(locale), "decision": "escalate"}


def _terminal_step(cs, locale) -> dict:
    return {"message": t(locale, "terminal"), "chips": []}


def _run_vision(conversation, cs, events, locale):
    """Extract nameplate fields from an uploaded photo (recorded as a tool turn)."""
    try:
        part = gemini.file_part(conversation.messages.filter(image__isnull=False).last().image.path)
        system = ('Extract from this equipment nameplate photo. JSON only: '
                  '{"manufacturer": "", "model": "", "serial": "", "error_code": ""}.')
        resp = gemini.generate([part], model=prompts.model_for("specialist"),
                               system_instruction=system, response_mime_type="application/json",
                               max_output_tokens=150)
        data = _parse_json(resp.text)
    except Exception:  # noqa: BLE001
        data = {}
    model = sanitize.clean_model(str(data.get("model") or ""))  # S3: whitelist OCR fields
    if model:
        cs["slots"]["nameplate_photo"] = True
        cs["slots"]["model"] = cs["slots"].get("model") or model
        cs["slots"]["serial"] = cs["slots"].get("serial") or sanitize.clean_model(str(data.get("serial") or ""))
        cs["slots"]["error_code"] = (cs["slots"].get("error_code")
                                     or sanitize.clean_error_code(str(data.get("error_code") or "")))
        cs["slots"]["brand"] = cs["slots"].get("brand") or sanitize.clean_lead_field(str(data.get("manufacturer") or ""), 40)
        cs["slots"]["ocr_text"] = sanitize.cap(" ".join(str(v) for v in data.values() if v), 120)
    Message.objects.create(conversation=conversation, role="tool", tool_name="vision_extract",
                           tool_result=data)
    events.append({"type": "tool_result", "name": "vision_extract", "result": data})


def _handoff_line(locale: str) -> str:
    return t(locale, "handoff")


def _escalation_chips(locale: str = "en") -> list[dict]:
    return [{"value": "yes_send", "label": t(locale, "chip_yes_send")},
            {"value": "not_yet", "label": t(locale, "chip_not_yet")}]
