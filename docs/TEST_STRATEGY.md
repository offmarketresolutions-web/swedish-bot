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

---

# Production-readiness test plan (2026-08-11)

Measured state: **634 passed, 1 skipped, 15 deselected** (`-m 'not live'`, 14m21s) across ~48 test
modules + 19 scenario files + 10 Playwright e2e. That suite is healthy — and it did **not** catch
any of the three bugs found today.

## The systemic gap this plan exists to close

All three of today's bugs were invisible to the whole suite, for one shared reason: **every test
builds a freshly seeded world, but production runs a drifted one.**

| Bug | Why 634 tests missed it |
|---|---|
| Manual-mode retrieval saw only the machine's LEAF category | Fixture corpora are tiny, so a too-narrow filter still returned *something*. Nothing asserted the *right* entry came back — only that retrieval was non-empty. |
| Owner-edited prompts never gained the new contract keys | Every test calls `seed_kb` first, so `AgentPrompt.body` is always the current repo default. The prod state (9 drifted rows) was never simulated. |
| LLM judge silently scored nothing (`llm == {}`) | The harness had no test at all — `tools/eval/` is unowned by the suite. |

Three test tiers are missing, in priority order.

### Tier A — "production-shaped" fixtures (highest leverage)

A `drifted` fixture that seeds, then **overwrites prompt bodies with the previous release's text**
and leaves owner-style edits in place. Run the golden scenarios against it. Any feature that
depends on a contract key added after that release fails loudly instead of silently.

```python
@pytest.fixture
def drifted(seeded):
    """Prod shape: prompts the owner edited before the current release."""
    for role, body in JULY_PROMPT_BODIES.items():
        AgentPrompt.objects.filter(role=role).update(body=body)

def test_reassure_close_still_fires_on_a_drifted_prompt(drifted, mock_gemini):
    # RED before chat/prompts.py::contract_addendum existed.
    out = process_turn(conv, "there's a bit of condensation, is that normal?")
    assert ServiceRequest.objects.count() == 0
```

### Tier B — meta-guards (cheap, catch whole bug classes)

```python
def test_every_contract_key_the_backend_reads_is_declared_to_the_role(seeded):
    """Guard for the 2026-08-11 class: data.get(key) against a prompt that never emits key."""
    for role, keys in CONTRACT_KEYS_BY_ROLE.items():
        rendered = prompts.render(role)
        for key in keys:
            assert key in rendered, f"{role} never told to emit {key}"

def test_retrieval_canary_returns_the_expected_entry(seeded):
    """Guard for the leaf-scope class: assert the RIGHT row, not merely a non-empty list."""
    for query, expected_key in RETRIEVAL_CANARIES:      # incl. a bound-machine manual-mode case
        hits = rank_general_knowledge(query, ...)
        assert expected_key in {f.key for f, _ in hits}
```

`RETRIEVAL_CANARIES` must include at least one **manual-mode** case (machine bound), because that
is the path where the leaf-scope bug lived and general-mode tests passed throughout.

### Tier C — the eval harness itself is production code

`tools/eval/` had zero tests and silently produced no rubric scores across 186 records. Minimum:
`judge.py` returns populated `llm` scores for a fixture record; a `--no-llm` record is never reused
as a cached LLM verdict (the actual cache-poisoning bug); `report.py` excludes infra-skipped rows
from both numerator and denominator.

## Ranked gaps (what is still unverified)

| # | Gap | Type | Risk | Status |
|---|---|---|---|---|
| 1 | **Playwright e2e not re-run since 2026-07-14** — orchestrator, prompts and retrieval have all changed since | e2e | **High** — the only tier that exercises the real browser + widget + form chip | Must run before deploy |
| 2 | Live 100-conversation eval | behavioral | High | Quota-blocked; auto-resuming |
| 3 | Deploy path against a **drifted** prod DB (`post_deploy` chain + `selfcheck` + `agent_config_diff`) | integration | High | `test_post_deploy.py` exists but seeds fresh — Tier A applies |
| 4 | General mode with an **approved** FAQ corpus | behavioral | Medium | Approved in eval DB only; prod is 1/93 (owner action) |
| 5 | Service-area gate **ON** (`GeoSettings.enabled=True`) incl. Bylunds/Nordborr override | integration + live | Medium | Unit-tested only; never exercised live |
| 6 | Voice (Vapi) + WhatsApp end-to-end | e2e | Medium | 21 unit tests; blocked on owner credentials |
| 7 | Single-user latency vs the 2–5s v1 budget | perf | Medium | Never measured outside the saturated eval driver |
| 8 | Cross-customer dedup / PII purge completeness | integration | **High if wrong** | Under audit now |

## TDD policy for the remaining work

The Iron Law applies to every item above and every audit finding: **no production code without a
failing test first.** Concretely, for this codebase:

1. Bug fixes get a test that reproduces the bug *from the outside* (a conversation turn or a
   `render()`/`rank()` call), not one that asserts the internals of the fix.
2. "Watched it fail" means pasting the RED output. A test written after the fix passes immediately
   and proves nothing — that is exactly how the contract bug survived.
3. Assert the **right** result, never merely a non-empty one. Both the retrieval and contract bugs
   would have been caught by one stricter assertion.
4. Live-API tests stay `@pytest.mark.live` and out of the default run; behavioral claims about the
   bot come from the eval harness, not from mocked tests.
5. Fixes driven by an eval failure carry the failing spec id in the test name/docstring
   (e.g. `test_..._regression_R018`) so the transcript is traceable.

## Coverage targets

- Safety guardrails, escalation, lead capture, identification, PII purge: **~100%**, plus a
  meta-guard that the contract for each is actually delivered to the model.
- Retrieval: every role × representative-query canary, asserting the expected entry.
- Harness (`tools/eval/`): judge/report/sim scoring logic covered; the driver itself stays manual.
- Skip: `__str__`, framework glue, dashboard cosmetics, one-off scripts.
