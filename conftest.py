"""Pytest harness. Gemini is mocked by default (deterministic, offline, free).
A `live` marker opts into real Vertex calls: `uv run pytest -m live`.

The mock is CONTENT-AWARE: it classifies each call by its system prompt (intake
extractor / router / specialist / safety / vision / intelligent-intake) and
returns a sensible default, so the multi-call FSM works without scripting every
call. Tests override per role via `mock_gemini.responses[role] = {...}`.
"""
from __future__ import annotations

import json as _json
import re as _re

import pytest

from core.services import gemini as gemini_mod

_REPLY_RE = _re.compile(r"Reply:\s*(.+)", _re.DOTALL)


def _classify(system: str) -> str:
    s = system or ""
    if "extract one field" in s:
        return "extractor"
    if "safety backstop" in s:
        return "safety"
    if "routing classifier" in s:
        return "router"
    if "senior Nordland VVS service technician" in s:
        return "specialist"
    if "service coordinator handling equipment we do NOT" in s:
        return "intelligent_intake"
    if "nameplate photo" in s:
        return "vision"
    if "quality and safety reviewer" in s:
        return "qa"
    return "other"


class FakeGemini:
    def __init__(self):
        self.responses: dict[str, object] = {}  # role -> dict/str override
        self.calls: list[dict] = []

    def _default(self, role: str, contents) -> object:
        if role == "safety":
            return {"unsafe": False, "reason": ""}
        if role == "router":
            return {"severity": "normal", "supported": True}
        if role == "extractor":
            m = _REPLY_RE.search(contents if isinstance(contents, str) else "")
            return {"on_target": True, "value": (m.group(1).strip() if m else "")}
        if role == "vision":
            return {}
        if role == "specialist":
            return {"answer_to_customer": "Let me check.", "confidence": 0.0,
                    "decision": "escalate", "in_docs": False, "report": {}}
        if role == "intelligent_intake":
            return {"answer_to_customer": "I'll get a Nordland technician to help.",
                    "decision": "escalate", "severity": "normal", "report": {}}
        return "OK"

    def generate(self, contents, *, model, system_instruction=None, **kw):
        role = _classify(system_instruction or "")
        self.calls.append({"role": role, "model": model, "contents": contents})
        resp = self.responses.get(role)
        if resp is None:
            resp = self._default(role, contents)
        text = resp if isinstance(resp, str) else _json.dumps(resp)
        cached = 120_000 if kw.get("cached_content") else 0
        return gemini_mod.GeminiResponse(
            text=text, model=model, prompt_tokens=cached + 200,
            completion_tokens=max(len(text) // 4, 1), cached_tokens=cached,
            cost_usd=0.0, auth_mode="mock")

    def generate_stream(self, contents, *, model, **kw):
        class _Chunk:
            def __init__(self, t):
                self.text = t
                self.usage_metadata = None
        yield _Chunk("OK")

    def create_cache(self, **kw):
        return "mock/cache/abc123"

    def file_part(self, path, *, mime_type=None):
        return {"__mock_part__": path}

    def health_check(self):
        return {"mode": "mock", "ready": True, "reason": "mock"}


@pytest.fixture
def mock_gemini(monkeypatch):
    fake = FakeGemini()
    for name in ("generate", "generate_stream", "create_cache", "file_part", "health_check"):
        monkeypatch.setattr(gemini_mod, name, getattr(fake, name))
    return fake
