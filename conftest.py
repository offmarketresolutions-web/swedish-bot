"""Pytest harness. Gemini is mocked by default (deterministic, offline, free).
A `live` marker opts into real Vertex calls: `uv run pytest -m live`."""
from __future__ import annotations

import json as _json

import pytest

from core.services import gemini as gemini_mod


class FakeGemini:
    """Scriptable stand-in for core.services.gemini.

    Tests push responses (str or dict→JSON) in the order the agents will call;
    each `generate()` pops the next. A dict is serialized to JSON text so agents
    that parse structured output work unchanged. Records calls for assertions."""

    def __init__(self):
        self._queue: list = []
        self.calls: list[dict] = []
        self.default = "OK"

    def push(self, *responses):
        for r in responses:
            self._queue.append(r)
        return self

    def _next_text(self) -> str:
        if self._queue:
            r = self._queue.pop(0)
            return r if isinstance(r, str) else _json.dumps(r)
        return self.default

    def generate(self, contents, *, model, **kw):
        self.calls.append({"contents": contents, "model": model, **kw})
        text = self._next_text()
        # realistic-ish token counts; cached when a cache is attached
        cached = 120_000 if kw.get("cached_content") else 0
        prompt = cached + 200
        return gemini_mod.GeminiResponse(
            text=text, model=model, prompt_tokens=prompt,
            completion_tokens=max(len(text) // 4, 1), cached_tokens=cached,
            cost_usd=0.0, auth_mode="mock",
        )

    def generate_stream(self, contents, *, model, **kw):
        class _Chunk:
            def __init__(self, t):
                self.text = t
                self.usage_metadata = None
        yield _Chunk(self._next_text())

    def create_cache(self, **kw):
        return "mock/cache/abc123"

    def file_part(self, path, *, mime_type=None):
        return {"__mock_part__": path, "mime": mime_type}

    def health_check(self):
        return {"mode": "mock", "ready": True, "reason": "mock"}


@pytest.fixture
def mock_gemini(monkeypatch):
    fake = FakeGemini()
    for name in ("generate", "generate_stream", "create_cache", "file_part", "health_check"):
        monkeypatch.setattr(gemini_mod, name, getattr(fake, name))
    return fake
