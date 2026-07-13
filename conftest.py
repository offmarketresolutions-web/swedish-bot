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
    if "pull out every field" in s:  # bulk multi-fact extractor (chat.intake.bulk_extract)
        return "bulk"
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
    if "nameplate photo" in s or "rating plate" in s.lower():
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
        if role == "bulk":
            # bulk_extract: default states nothing (all null) so it never fabricates slots;
            # tests that exercise multi-fact mining override mock_gemini.responses["bulk"].
            return {"category": None, "subtype": None, "brand": None, "model": None,
                    "error_code": None, "alarm_text": None, "onset": None, "postal_code": None,
                    "installer": None, "operating_context": None, "readings": [], "problem": None}
        if role == "specialist":
            return {"answer_to_customer": "Let me check.", "confidence": 0.0,
                    "decision": "escalate", "in_docs": False,
                    "extracted_facts": {"onset": None, "alarm_text": None, "model_text": None,
                                        "error_code": None, "readings": [], "installer": None,
                                        "operating_context": None, "check_results": []},
                    "report": {}}
        if role == "intelligent_intake":
            return {"answer_to_customer": "I'll get a Nordland technician to help.",
                    "decision": "escalate", "severity": "normal", "report": {}}
        return "OK"

    def generate(self, contents, *, model, system_instruction=None, **kw):
        # classify by system prompt OR inlined instruction in contents (cached path)
        role = _classify((system_instruction or "") + " " + str(contents)[:4000])
        self.calls.append({"role": role, "model": model, "contents": contents, "kw": kw})
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

    def embed(self, texts, *, model=None, task_type="RETRIEVAL_DOCUMENT",
              output_dimensionality=None, api_key=None):
        import hashlib
        dim = output_dimensionality or 768
        one = isinstance(texts, str)
        items = [texts] if one else list(texts)

        def _vec(t):
            import math
            buf, i = [], 0
            while len(buf) < dim:  # full-entropy: keep hashing to fill `dim`
                h = hashlib.sha256(f"{t}:{i}".encode("utf-8")).digest()
                buf.extend((b / 255.0) * 2 - 1 for b in h)
                i += 1
            v = buf[:dim]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            return [x / n for x in v]  # normalized, like the real model

        out = [_vec(t) for t in items]
        return out[0] if one else out

    def create_cache(self, **kw):
        return "mock/cache/abc123"

    def file_part(self, path, *, mime_type=None):
        return {"__mock_part__": path}

    def health_check(self):
        return {"mode": "mock", "ready": True, "reason": "mock"}


@pytest.fixture
def mock_gemini(monkeypatch):
    fake = FakeGemini()
    for name in ("generate", "generate_stream", "embed", "create_cache", "file_part", "health_check"):
        monkeypatch.setattr(gemini_mod, name, getattr(fake, name))
    return fake


@pytest.fixture(autouse=True)
def _clear_cache():
    # LocMemCache persists across tests in one process; clear rate-limit counters
    # so tests don't bleed into each other.
    from django.core.cache import cache
    cache.clear()
    yield


@pytest.fixture(autouse=True)
def _semantic_off(settings):
    # Semantic (embedding) search is ON in production but OFF by default in tests so
    # unit tests stay offline + deterministic. Semantic tests opt in explicitly.
    settings.SEMANTIC_SEARCH_ENABLED = False
