"""Fetch the authoritative full conversation from Vapi (ported from budtender/voice/callfetch.py).

Pulls ``GET /call/{id}`` on demand (dashboard button / management command) and persists the full
transcript + summary onto the ``VapiCall`` row and every tool invocation into ``ToolCallLog``
(``source="vapi_fetch"``). Read-only against Vapi; idempotent upserts, safe to re-run.
"""

from __future__ import annotations

import json
import logging

from core.services import vapi
from voice import guardrails

logger = logging.getLogger(__name__)


def _coerce_args(value) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def parse_tool_calls(messages: list) -> list[dict]:
    invocations: dict[str, dict] = {}
    order: list[str] = []
    results: dict[str, object] = {}
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("toolCalls") or msg.get("toolCallList") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            tcid = tc.get("id") or tc.get("toolCallId") or ""
            name = fn.get("name") or tc.get("name") or ""
            key = tcid or f"{name}:{len(order)}"
            if key not in invocations:
                order.append(key)
            invocations[key] = {
                "tool_call_id": tcid, "name": name,
                "args": _coerce_args(fn.get("arguments", tc.get("arguments"))),
            }
        rid = msg.get("toolCallId")
        if rid is not None and ("result" in msg or msg.get("role") == "tool_call_result"):
            results[rid] = msg.get("result")
    rows = []
    for key in order:
        inv = invocations[key]
        rows.append({**inv, "result": results.get(inv["tool_call_id"])})
    return rows


def fetch_full_conversation(call_id: str) -> dict:
    raw = vapi.get_call(call_id) or {}
    artifact = raw.get("artifact") or {}
    transcript = guardrails.redact_pii(artifact.get("transcript") or "")
    messages = artifact.get("messages") or []
    summary = guardrails.redact_pii((raw.get("analysis") or {}).get("summary") or "")
    tool_calls = parse_tool_calls(messages)
    persisted = _persist(call_id, raw, transcript, summary, tool_calls)
    return {"call_id": call_id, "transcript": transcript, "summary": summary,
            "messages": messages, "tool_calls": tool_calls, "persisted": persisted}


def _persist(call_id: str, raw: dict, transcript: str, summary: str, tool_calls: list[dict]) -> dict:
    from voice.models import ToolCallLog, VapiCall

    vc, _ = VapiCall.objects.get_or_create(
        call_id=call_id, defaults={"assistant_id": raw.get("assistantId", "") or ""})
    fields: list[str] = []
    if transcript:
        vc.transcript = transcript
        fields.append("transcript")
    if summary and not vc.ai_summary:
        vc.ai_summary = summary
        fields.append("ai_summary")
    if fields:
        fields.append("updated_at")
        vc.save(update_fields=fields)

    n = 0
    for tc in tool_calls:
        ToolCallLog.objects.update_or_create(
            call_id=call_id, tool_call_id=tc.get("tool_call_id") or "", name=tc.get("name") or "",
            defaults={"args": guardrails.redact_pii(tc.get("args") or {}),
                      "result": guardrails.redact_pii(tc.get("result") or {}),
                      "source": "vapi_fetch"},
        )
        n += 1
    return {"voice_call": vc.pk, "tool_calls": n}
