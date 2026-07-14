# Thread continuity spike — 2026-07-14

## Ask

Owner pasted marketing copy about the Gemini "Interactions API" and its
`previous_interaction_id` / SDK `chats` objects, asking whether we should
adopt server-side conversation continuation "so we don't have to re-ingest
all the messages once again."

Scope: spike with real Vertex probes, implement only what the numbers justify.
Files touched: `core/services/gemini.py` (none needed), `chat/context.py`
(none needed), this doc, `tests/test_thread_continuity_spike.py`.
`chat/orchestrator.py` (owns `_history_parts`, the actual resend site) was
explicitly out of scope for edits — see the diff proposal at the bottom if a
future change is ever warranted there.

## Current state (verified by reading the code, not assumed)

- `chat/orchestrator.py::_history_parts` rebuilds the transcript every turn
  from `conversation.messages`, capped to the last 14 messages
  (`max_msgs=14`) and 4 images (`max_imgs=4`), wrapped as untrusted DATA.
  This is already the token-budget guard the brief asked (b)/(a) to add —
  it exists today, pre-dating this spike.
- `chat/context.py::machine_pdf_context` already does explicit Vertex context
  caching, but only for the **manual PDFs** (the large, static, per-machine
  part) — not conversation history. Below `CACHE_MIN_TOKENS` it inlines
  instead of caching (`core/constants.py: CACHE_MIN_TOKENS = 4096`).
- `system_instruction`, `tools`, and `generation_config` are sent fresh on
  every `generate()` call regardless of caching — the owner's own pasted
  material concedes the Interactions API doesn't carry those either.
- Conversations run 2–25 turns; `MAX_TOTAL_TURNS = 25` is a hard ceiling
  (`chat/orchestrator.py:172`).
- SDK: `google-genai==2.9.0` (pinned in `uv.lock`), Vertex mode
  (`vertexai=True, project=..., location=europe-north1` in prod /
  `us-central1` in the dev project used for this spike).

## Spike 1 — Interactions API / `previous_interaction_id` on Vertex

The installed SDK (2.9.0) *does* expose `client.interactions` (a
`GeminiNextGenInteractions` resource with `.create()` / `.get()`), and it
*does* route through the Vertex endpoint when the client is built with
`vertexai=True, project=..., location=...` (confirmed by reading
`google/genai/_gaos/google_genai.py::get_google_genai_api_version`, which
prefixes the path with `/projects/{project}/locations/{location}` when
`api_client.vertexai` is set — so this is not an AI-Studio-only surface at
the SDK level).

**Live probe** (against the project's real Vertex creds, `us-central1`):

```python
client, mode = gemini.make_client()          # mode == "vertex"
client.interactions.create(model="gemini-2.5-flash", input="Say OK.")
```

Result for every model we actually use (`gemini-2.5-flash`,
`gemini-2.5-flash-lite`, `gemini-2.5-pro`, and for completeness
`gemini-3-pro-preview`, `gemini-flash-latest`):

```
400 Bad Request — {"error": {"message": "Unsupported model interaction: <model>", "code": "invalid_request"}}
```

**Verdict: not usable.** The Interactions API endpoint exists and accepts
requests, but rejects the entire Gemini 2.x/3.x model family we're on with
"Unsupported model interaction" — this looks like an agent-platform feature
gated to specific agent-oriented models/configs, not a general drop-in
replacement for `generate_content`. Nothing here is actionable today.
Pinned as `tests/test_thread_continuity_spike.py::test_live_interactions_api_unsupported_for_our_models_on_vertex`
(marked `live`) so a future SDK/project change that makes this start
succeeding is caught, not silently missed.

The SDK also has a `client.chats` convenience object, but it is a client-side
helper that wraps `generate_content` and resends the full history itself
under the hood — it is not a server-side continuation mechanism and doesn't
change the token-resend math below.

## Spike 2 — explicit context caching of conversation history

`CACHE_MIN_TOKENS = 4096` is the floor already coded into `chat/context.py`
(confirmed against Vertex docs for `gemini-2.5-flash`: minimum cacheable
content is 4,096 tokens, min TTL 1s, storage billed per-hour after that).

**Measured** (live `count_tokens` call, `gemini-2.5-flash`, realistic Swedish
customer/assistant turn pairs — a leaky heat-pump complaint + a clarifying
question, ~50 words each turn):

| Turns | Chars | Tokens (measured) | vs. CACHE_MIN_TOKENS (4096) |
|------:|------:|-------------------:|:-----------------------------|
| 5     | 1,005 | 241                 | 6% of floor |
| 15    | 3,015 | 721                 | 18% of floor |
| 25 (hard ceiling) | 5,025 | 1,201     | 29% of floor |

Even at the **absolute maximum** conversation length (`MAX_TOTAL_TURNS=25`),
history is under a third of the minimum token count Vertex will even let you
cache. A conversation would need turns roughly **3.4x longer than this
already-verbose sample** to reach the cache floor at all — turns_avg would
have to run ~170 words each, every single turn, for 25 turns straight. Real
transcripts (see `docs/evals/2026-07-12-live-eval/`) run shorter than the
sample used here.

## The honest math

- History caching has **two costs that resend doesn't**: a cache-create
  round-trip (extra latency + a request) and per-hour storage billing for the
  TTL window, against a benefit of ~4x cheaper *input* tokens on the cached
  portion only (`PRICING_PER_1K["gemini-2.5-flash"]`: $0.0003/1k input vs.
  $0.000075/1k cached — i.e. cached tokens cost 25% of fresh input tokens).
- At 1,201 tokens (worst case), the raw dollar difference between resending
  and (hypothetically) caching that history is $0.0003 · 1.2 vs.
  $0.000075 · 1.2 ≈ **$0.00027 saved per turn** — before subtracting the
  cache-create cost and storage rent, which exceed that in every realistic
  scenario at this history size.
- `system_instruction` + `tools` + `generation_config` are NOT covered by any
  of this (both Interactions and caching) — they're sent fresh every call
  regardless, per the owner's own pasted material and confirmed by reading
  `core/services/gemini.py::generate`.
- Conclusion: **there is no conversation length inside our 2–25 turn range,
  or even several multiples past our hard ceiling, where caching or
  Interactions beats plain resend.** The manual-PDF caching that already
  exists in `chat/context.py::machine_pdf_context` is the only place caching
  pays off, because manuals are large (routinely tens of thousands of
  tokens) and reused across many conversations — conversation history is
  neither.

## Verdict: (a) — nothing beyond what exists

- Resend is optimal at these lengths, by a wide margin — not a close call.
- The token-budget guard the brief asked for already exists:
  `chat/orchestrator.py::_history_parts(max_msgs=14, max_imgs=4)` plus the
  `MAX_TOTAL_TURNS=25` hard ceiling. No new flag, no `HISTORY_CACHE_ENABLED`,
  no cached-content plumbing was added — building that machinery here would
  violate the ponytail rule: the math above shows it wouldn't be exercised
  in the range this bot ever runs in.
- `core/services/gemini.py` and `chat/context.py` are unchanged. This spike
  produced evidence and two pinned regression tests, not new production code.

## If this ever needs revisiting

Re-run this spike if any of these change:
1. `MAX_TOTAL_TURNS` is raised well past 25 (multiply the table above
   linearly; it would need to roughly 4x before even approaching the floor).
2. Per-turn content balloons (e.g. embedding full OCR dumps or long manual
   excerpts into every history turn instead of just the conversational text).
3. Google ships Interactions support for `gemini-2.5-*`/`gemini-3-*` on
   Vertex — `test_live_interactions_api_unsupported_for_our_models_on_vertex`
   will start failing (in the good way) as the trip wire.

## Orchestrator wiring — not needed

No diff proposed against `chat/orchestrator.py`. The existing
`_history_parts` truncation is already the correct, sufficient guard; nothing
in this spike's findings calls for changing it.
