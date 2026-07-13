# Nordland VVS — Real-browser E2E suite (2026-07-13)

Real Chromium (Playwright sync API) driving the live dev server on
`http://127.0.0.1:8077` against the dev **`nordland`** DB (never `eval_nordland`).
The chat scenarios hit **real Vertex Gemini** — no mocks. `tools/eval` and the
`2026-07-12-*` eval dirs were not touched.

- Suite: `tests/e2e/test_browser.py` (+ `tests/e2e/conftest.py`)
- Screenshots: `docs/evals/2026-07-13-e2e/*.png`
- Server stdout/stderr: `docs/evals/2026-07-13-e2e/server.log`

## Result: 6 / 6 PASS

| # | Scenario | Test | Result | Screenshots |
|---|----------|------|--------|-------------|
| a | Homepage clone renders (hero, 3 service cards, widget launcher) | `test_a_homepage_renders` | PASS | `a_homepage.png` |
| b | Full widget conversation (live Gemini), chips render + click → next reply | `test_b_widget_conversation` | PASS | `b1_after_chip.png`, `b2_live_reply.png` |
| c | Photo upload through the widget file input (vision runs live) | `test_c_photo_upload` | PASS | `c_photo_upload.png` |
| d | Escalation → **ServiceRequest lead row created in DB** | `test_d_escalation_creates_lead` | PASS | `d_escalation.png` |
| e | Dashboard login + full sidebar walk + machine-doc modal | `test_e_dashboard` | PASS | `e01_*`…`e13_doc_modal.png` |
| f | Mobile 375px: homepage + widget open/close | `test_f_mobile` | PASS | `f1_mobile_home.png`, `f2_mobile_widget_open.png`, `f3_mobile_widget_closed.png` |

### Timing (two representative full runs — live latency varies a lot)
- Fast run: **33s** total (test_d 13s, test_b 5.5s, test_c 2.7s, test_e 2.9s).
- Slow run: **215s** total (test_d **134s** — a full 9-turn live escalation; test_c 33s; test_f 30s).
Per-turn wait budget is 40s; the escalation walk is up to ~16 live turns, so a slow
Gemium window pushes test_d into the low minutes. All other tests are seconds.

## Per-scenario notes

- **(a)** Asserts the exact hero `<h1>` "Din auktoriserade värmepumpsinstallatör",
  the three service-card headings (Värmepumpar / Vattenpumpar / Vattenbrunnar), and
  the `[data-testid="widget-bubble"]` launcher visible.
- **(b)** Greeting renders category quick-replies (asserted), a chip click
  ("Värmepump") returns the next Swedish reply, then the free-text
  `"Min IVT värmepump visar larm H01 5252"` returns a live Swedish reply.
  Note: I click the guaranteed greeting chip **before** the free-text send (the
  task listed send-then-chip; the specialist answer for a fully-identified case
  returns no chips, so anchoring the chip assertion on the greeting's category
  quick-replies is the robust ordering). `b2_live_reply.png` shows the live turn
  with IVT model chips.
- **(c)** A generated nameplate-style PNG is attached via the widget's hidden
  `input[type=file]`; the user bubble shows `📷 nameplate.png` and a live bot reply
  follows (vision + intake ran).
- **(d)** Unsupported-brand path (`"Jag har en NIBE pump som låter konstigt"`) →
  the FSM's intelligent-intake escalation. A stage-driven loop supplies
  name/phone (+ skips email) / postal and clicks **"Ja, skicka till Nordland"**.
  Asserted in the **live `nordland` DB**: `ServiceRequest` count went up by 1,
  `escalation_reason == "unsupported"`, and the linked `Customer` has a captured
  phone. (This is a genuine write to the dev DB — see cleanup note below.)
- **(e)** Logs in through the real `/admin/login/` form as a seeded superuser
  (`e2e_admin`), then visits every sidebar route (overview, analytics, sessions,
  customers, voice phone, voice credentials, settings, KB, FAQ, guardrails, flow,
  homepage-demo) asserting HTTP 200 + a key selector, and opens the customer-detail
  **docs** tab → machine-documentation modal (`#mdoc-<id>` with the PDF iframe).
- **(f)** 375×812 mobile emulation: homepage hero visible, widget opens (full-screen
  sheet) and closes. Open is fired via `dispatch_event("click")` — see flakiness note.

## Product bug found (documented, not patched — no prod code changed)

**Lead dispatch can crash when the guardrail supplies a long escalation reason.**
`chat/guardrails.py:is_unsafe()` returns an arbitrary-length LLM `reason`
(`str(data.get("reason",""))`). That flows unbounded into
`chat/orchestrator.py` → `cs["escalation_reason"]` → `crm/leads.py:create_and_dispatch`
→ `ServiceRequest.escalation_reason`, which is **`CharField(max_length=120)`**
(`crm/models.py:188`). A reason longer than 120 chars raises
`psycopg.errors.StringDataRightTruncation: value too long for type character
varying(120)` and the whole turn 500s — the lead is lost.

Evidence: the concurrent live eval already hit this in
`docs/evals/2026-07-12-live-eval/results.jsonl` (record `R013`), traceback ending:
```
crm/leads.py line 82, in create_and_dispatch
    sr, _ = ServiceRequest.objects.get_or_create(idempotency_key=..., defaults={... "escalation_reason": reason})
django.db.utils.DataError: value too long for type character varying(120)
```
This suite's (d) does **not** trip it because the unsupported path uses the short,
code-controlled reason `"unsupported"` (11 chars). A safety-veto escalation with a
verbose LLM reason is the trigger. **Not marked xfail** (it doesn't block any test
here) — flagged for a fix: truncate the reason at capture (e.g. `reason[:120]`) or
widen the column. Suggested root-cause fix: clamp in `is_unsafe`/orchestrator where
the reason is assigned, since it is also stored on `Session` and shown to staff.

## How to re-run

```bash
# from repo root, with the compose `db` service up and .env Vertex creds present
uv sync                              # (deps already added: playwright, pytest-playwright)
uv run playwright install chromium   # one-time browser download

# full suite (boots its own dev server on :8077, tears it down after)
uv run pytest -m e2e tests/e2e -v

# a single scenario
uv run pytest -m e2e tests/e2e/test_browser.py -k test_d_escalation -v

# the default suite still SKIPS e2e (tests are marked e2e + live; addopts is -m 'not live')
uv run pytest
```

The dev server is managed by the `dev_server` session fixture (started with
`--noreload`, health-probed on `/admin/login/`, terminated on teardown). If a server
is already listening on :8077 it is reused instead of double-bound.

## Cleanup / side effects
- The dev server process is always torn down by the fixture (verified: no LISTENING
  socket on :8077 after the run).
- Scenario (d) writes a real `ServiceRequest` + `Customer` ("Erik Testsson") to the
  dev DB each run, and (e)/seed create a superuser `e2e_admin` and a customer
  "E2E Testkund" (idempotent). These are intentional live-DB artifacts of an
  end-to-end lead flow, not cleaned up automatically.
