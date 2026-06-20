"""The orchestrator FSM (plan §6). Deterministic in code: counts turns, owns
CaseState, routes to exactly one agent per turn, runs the guardrail backstop,
flushes structured facts to crm.Session. The LLM never controls the flow.
"""
from __future__ import annotations

import json
import re

from chat import context, guardrails, intake, prompts
from chat.casestate import (
    flush_to_session,
    is_routable,
    new_case_state,
    next_required_slot,
)
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


def _parse_json(text: str) -> dict:
    try:
        return json.loads(_FENCE.sub("", text or "").strip())
    except Exception:  # noqa: BLE001
        return {}


# ── public API ────────────────────────────────────────────────────────

def open_conversation(language: str = "en") -> tuple[Conversation, dict]:
    conv = Conversation.objects.create(language=language, case_state=new_case_state())
    cs = conv.case_state
    cs["current_slot"] = "category"
    conv.case_state = cs
    conv.save(update_fields=["case_state"])
    return conv, {
        "message": intake.GREETING + " " + intake.QUESTION["category"],
        "chips": intake.chips_for("category", cs, language),
        "state": STATE_INTAKE,
    }


def process_turn(conversation: Conversation, user_text: str = "", image=None) -> dict:
    locale = conversation.language
    cs = conversation.case_state or new_case_state()
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
        else:  # ESCALATE / RESOLVED
            return _terminal_step(cs, locale)
    return {"message": _handoff_line(locale), "chips": _escalation_chips()}


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
                return {"message": "Sorry, I didn't quite catch that. " + intake.QUESTION.get(current, ""),
                        "chips": intake.chips_for(current, cs, locale)}
    if is_routable(cs):
        cs["state"] = STATE_ROUTING
        return None
    nxt = next_required_slot(cs)
    if nxt is None:
        cs["state"] = STATE_ROUTING
        return None
    cs["current_slot"] = nxt
    return {"message": intake.QUESTION[nxt], "chips": intake.chips_for(nxt, cs, locale)}


def _route(conversation, cs, events, locale):
    from kb.models import Category, ProblemCategory

    s = cs["slots"]
    query = " ".join(x for x in [s.get("brand"), s.get("model"), s.get("ocr_text")] if x and x != "unknown")
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
        "router", locale=locale, equipment=json.dumps(cs["slots"]),
        problem=cs["slots"].get("problem", ""), ocr_text=cs["slots"].get("ocr_text") or "",
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
    turn = f"Customer problem: {cs['slots'].get('problem','')}. Error code: {cs['slots'].get('error_code') or 'none'}."
    contents = [turn] + inline
    resp = gemini.generate(contents, model=prompts.model_for("specialist"), system_instruction=system,
                           cached_content=cached, response_mime_type="application/json", max_output_tokens=700)
    data = _parse_json(resp.text)

    answer = data.get("answer_to_customer", "") or ""
    conf = float(data.get("confidence") or 0.0)
    if cs.get("match_confidence", 0) < 0.6:
        conf = min(conf, 0.5)
    if data.get("in_docs") is False:
        conf = min(conf, 0.6)
    cs["confidence"] = conf
    cs["decision"] = data.get("decision") or "escalate"
    cs["severity"] = data.get("severity") or cs.get("severity") or "normal"
    cs["report"].update({k: v for k, v in (data.get("report") or {}).items() if v is not None})

    unsafe, reason = guardrails.is_unsafe(answer, locale=locale)
    if unsafe or conf < CONFIDENCE_GATE or cs["decision"] != "solve" or forced:
        cs["state"] = STATE_ESCALATE
        cs["decision"] = "escalate"
        cs["report"]["service_recommended"] = True
        why = reason or ("low_confidence" if conf < CONFIDENCE_GATE else ("budget" if forced else "decision"))
        events.append({"type": "escalate", "reason": why})
        msg = (answer + "\n\n" if answer and not unsafe else "")
        return {"message": msg + _handoff_line(locale), "chips": _escalation_chips(),
                "decision": "escalate", "model": prompts.model_for("specialist")}

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
    answer = data.get("answer_to_customer") or _handoff_line(locale)
    events.append({"type": "escalate", "reason": "unsupported"})
    return {"message": answer, "chips": _escalation_chips(), "decision": "escalate"}


def _terminal_step(cs, locale) -> dict:
    return {"message": _handoff_line(locale), "chips": _escalation_chips()}


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
    if data.get("model"):
        cs["slots"]["nameplate_photo"] = True
        cs["slots"]["ocr_text"] = " ".join(str(v) for v in data.values() if v)
        cs["slots"]["brand"] = cs["slots"].get("brand") or data.get("manufacturer")
        cs["slots"]["model"] = cs["slots"].get("model") or data.get("model")
        cs["slots"]["serial"] = cs["slots"].get("serial") or data.get("serial")
        cs["slots"]["error_code"] = cs["slots"].get("error_code") or data.get("error_code")
    Message.objects.create(conversation=conversation, role="tool", tool_name="vision_extract",
                           tool_result=data)
    events.append({"type": "tool_result", "name": "vision_extract", "result": data})


def _handoff_line(locale: str) -> str:
    return ("Based on what you've described, this is best handled by a Nordland VVS "
            "technician so we get it exactly right. Shall I send your details to them?")


def _escalation_chips() -> list[dict]:
    return [{"value": "yes_send", "label": "Yes, send to Nordland"},
            {"value": "not_yet", "label": "Not yet"}]
