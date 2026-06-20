# Test Strategy — Nordland VVS Support Bot

Pyramid: **many fast unit tests**, **some integration tests** (Gemini mocked), **a small golden-set** of behavioral e2e tests. Gemini is mocked by default (deterministic, free, offline); a few `@pytest.mark.live` tests exercise real Vertex and are opt-in (`-m live`).

## Harness
- `pytest` + `pytest-django`, `DJANGO_SETTINGS_MODULE=config.settings`.
- `conftest.py`: `mock_gemini` fixture monkeypatches `core.services.gemini.generate/generate_stream/create_cache/file_part` to return scripted responses — no network, no cost. `live` marker for real-Vertex tests.
- Run: `make test` (mocked) · `uv run pytest -m live` (real Gemini).

## Coverage by component

| Area | Type | What we assert |
|------|------|----------------|
| `core.constants` cost | unit | cached tokens billed at cached rate, no double-count; unknown model **raises** (never $0). |
| `core.services.gemini` | unit | clock shim patches `utcnow`; `file_part` builds inline Part; auth-mode resolution. |
| `kb` models | unit | Vendor/Category/Machine/Document/AgentPrompt/FAQ/Chip invariants; i18n `*Text` fallback to `en`. |
| **trigram identification** | unit | "IVT 490" / "ivt490" / nameplate-OCR noise → correct Machine; score < 0.6 → unsupported. |
| `chat` models | unit | thin Conversation/Message; tool-role photo artifact; append-only. |
| `crm` models | unit | Session canonical reporting columns; ServiceRequest idempotency_key stable pre-insert; LeadDelivery UNIQUE(req,sink). |
| **agent FSM** | integration | intake slot-fill + extraction (mocked); router pick PDF; specialist solve vs escalate; CaseState→Session flush. |
| **guardrails** | unit | forbidden-class drafts (electrical/refrigerant/pressure) vetoed → escalate; confidence<0.80 → escalate. |
| reply budget | unit | counts assistant turns; contact+approval exempt; wrap-up at remaining≤1. |
| **lead sinks** | integration | DB sink always writes; email sink sends; disabled sinks skip+log; one sink failing doesn't block others; idempotent re-fire. |
| dashboard | integration | auth required; per-session page renders transcript + fields; metrics aggregate. |
| i18n | unit | `{language}` directive injected; chip/FAQ fallback. |
| **golden set** | e2e (mock+live) | the 5 plan cases: IVT-490 alarm, well low-pressure, unsupported brand, nameplate photo, dangerous→refuse+escalate. |

## Targets
- Business-critical paths (identification, guardrails, escalation, lead capture, cost): ~100%.
- Models/services: high. Skip trivial `__str__`, framework glue.
- Golden set: all 5 pass on mocks (CI) + spot-checked live before ship.
