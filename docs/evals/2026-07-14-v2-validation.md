# Swedish-bot v2 — Sprint S7 Final Validation

Date: 2026-07-13/14 · HEAD at start: `72e147c` · Full unit suite baseline: 493 passed / 1 skipped / 9 deselected.

This report covers: (1) Playwright E2E v2 extension, (2) the post-fix live-eval before/after
vs the frozen 60-record baseline, (3) the new v2-scope eval personas + run, (4) bugs fixed,
(5) honest gaps.

---

## 1. Playwright E2E (v2 extension)

New file: `tests/e2e/test_browser_v2.py` (4 scenarios, marked `e2e`+`live`, screenshots →
`docs/evals/2026-07-14-e2e-v2/`). Existing suite `tests/e2e/test_browser.py` (6 scenarios a–f)
is unchanged.

| # | Scenario | What it asserts | Result | Screenshot |
|---|----------|-----------------|--------|------------|
| a | postcode-early | rich opener → bot asks *postnummer* within first 2 questions | **PASS** (after product fix, see §4 bug 1) | `a_postcode_early.png` |
| b | model disambiguation | brand IVT + free-text "Geo" → disambiguation chips render, no machine asserted | **PASS** | `b_model_disambiguation.png` |
| c | form button + prefill | FormButton(quote_request) + escalate to lead → `<a target=_blank>` chip w/ `nl_case=` → `/demo/form?nl_case=<token>` prefilled | **PASS** | `c1_lead_done.png`, `c2_form_chip.png`, `c3_form_prefilled.png` |
| d | dashboard tabs | Service-area tab test box; Website & forms URL save round-trip; FAQ pending-approval section (102 unapproved: 92 FAQEntry + 10 SiteFAQ) | **PASS** | `d1`–`d4_*.png` |

Final combined run: `4 passed in 50.09s` (headless, live Gemini, single pass —
`docs/evals/2026-07-14-e2e-v2/run_full.log`). Flakiness fixes made properly, not papered
over: (i) first dashboard navigation gets a 60s timeout because the live-eval driver
saturating the shared dev DB/CPU pushed one `/dashboard/` load past the 15s context
default (observed once, transient); (ii) scenario-c phone assertion accepts the product's
correct E.164 normalization (`070-1234567` → `+46701234567`) — that was a test bug, not a
product bug.

---

## 2. Post-fix live eval — before / after

Datasets in `docs/evals/2026-07-12-live-eval/`:
- **Baseline (frozen, pre-fix)** `results.jsonl` — 60 records, `code_version=None` (old orchestrator).
  Composition: resolvable 31, escalate 22, unsupported 5, adversarial 2.
- **Post-fix** `results-postfix.jsonl` — 200-spec core run against the merged v2 fixes,
  converged by `drive_eval.py` (`EVAL_RESULTS_FILE=results-postfix.jsonl`).

### Infra incident found & fixed during S7 (2026-07-13 ~17:20)

The converging postfix driver had been failing **100% of new conversations since the v2
merge**: `eval_nordland` was never migrated to the v2 schema (`kb_faqentry.is_approved`
missing → `ProgrammingError` in every conversation touching FAQ retrieval), and carried
only the pre-v2 seed (7 vendors / no NIBE-CTC-Thermia brand vendors). 96 consecutive
error rows at `code_version=72e147c`; the 54 surviving good rows were all from pre-v2
code `4b87654`. Fix (S7): `migrate` + `seed_kb` (16 vendors) + `import_site_faq` +
`import_general_knowledge` (92 FAQEntry + 10 SiteFAQ, all unapproved) +
`seed_service_areas` (geo stays dormant) against `eval_nordland`. Driver recovered
immediately ([OK] records at 72e147c resumed).

**Dataset caveat:** `results-postfix.jsonl` is therefore mixed-version — ~54 records at
`4b87654` (conversation-gap fixes, pre-v2 routing) + the remainder at `72e147c` (full v2).
Every record carries `code_version`; per-version segmentation is included below.

### Headline: the 31 resolvable specs

| Metric | Baseline (pre-fix) | Post-fix |
|---|---|---|
| Resolvable outcome-match | **0 / 31** | _pending_ |
| Overall outcome-match | 24 / 59 | _pending_ |

Baseline resolvable actual-outcomes: `escalated_lead 23, safety_escalation 5, unsupported_lead 3`
— i.e. the old orchestrator escalated *every* resolvable case (never resolved), the exact
failure the v2 remedy/routing work targets.

_(Post-fix judged numbers filled in once the driver reaches ~200/200 good records and
`judge.py` + `report.py` run over `results-postfix.jsonl`.)_

---

## 3. v2-scope eval personas + run

`tools/eval/personas.py` extended with **40 new specs, ids V001–V040, `eval_set="v2"`**
(the 200 original specs are now `eval_set="core"`). `--set {core|v2|all}` wired into both
`runner.py` and `drive_eval.py`; `judge.py`/`report.py` honor `EVAL_RESULTS_FILE` and derive
`judged-*.jsonl` / `REPORT-*.md` / `transcripts-*/` per dataset.

v2 coverage (per the v2 scope):
- water pumps/wells — no-water, pressure-fluctuation, pump-cycling (V001–V008) → safe checks then lead; **never** pressure-switch adjustment
- water filters — staining, smell, regeneration (V009–V014) → safe checks then lead
- NIBE/CTC/Thermia — brand preserved, general mode, no fabricated alarm-code meaning (V015–V022)
- sudden-fault — ≤3 safe troubleshooting turns then service offer (V023–V027)
- always-been-cold comfort — documented user-setting guidance + original-value note (V028–V032)
- model ambiguity — "Geo 600" → disambiguation question, no machine from a guess (V033–V036)
- postcode flows — postnummer asked early, geo gate dormant (V037–V040)

Run command (after post-fix completes, to avoid quota contention):
```
EVAL_RESULTS_FILE=docs/evals/2026-07-12-live-eval/results-v2.jsonl \
POSTGRES_DB=eval_nordland python tools/eval/drive_eval.py --set v2   # workers 3 via PASS_PLAN
```
Pre-req (run once against `eval_nordland` before the v2 run): `migrate` + FAQ import +
`seed_service_areas`.

Status: _pending (gated on post-fix completion)_.

---

## 4. Bugs found & fixed (TDD, uncommitted diffs on main)

**Bug 1 — postcode-early skipped for rich openers** (found by e2e scenario a).
`chat/orchestrator.py::_intake_step` jumped to `STATE_ROUTING` as soon as
`is_routable()` (category+problem+identity) was true — a rich opener that filled those in
one message never got the early postnummer question; the postcode only surfaced at
lead-contact time. Fix: one postnummer ask before routing when `slots.postal_code` is
empty (already-stated or declined postcode skips; standard 2-reask→unknown machinery keeps
it non-blocking). Tests: `tests/test_casestate_s2.py::test_postcode_asked_even_when_rich_opener_makes_case_routable`
(RED→GREEN) + `test_postcode_not_reasked_when_rich_opener_contains_it`;
`tests/test_scenarios/test_i_edge.py::test_i2` updated to the new intended flow
(one postcode question then straight to `solve`). Verified end-to-end: e2e scenario a
passes live after the fix.

**Infra bug 2 — eval_nordland schema/seed drift** (found by transcript mining): see §2.
Not a product bug; fixed by running the documented DB prep. The lesson is recorded: the
eval DB must be re-migrated + re-seeded after every schema-bearing merge.

**Harness adjudication (not a fix):** `tools/eval/judge.py` outcome soft-ok extended with
`unsupported_lead → {escalated_lead}` — v2's three-way router deliberately sends
unlisted-but-serviced brands to the general specialist (escalates `low_confidence`/`budget`)
instead of v1's hard "unsupported" refusal. False-resolution remains a hard fail.

**Design-intent observations (documented, NOT fixed):**
- General mode is escalate-heavy while the 102-entry FAQ corpus is unapproved (retrieval
  sees an empty corpus) — BY DESIGN; approval is the owner's dashboard action.
- U009: "Welcome back — we've helped you before" to a first-time persona — the customer
  simulator reuses the same phone number (070-1234567) across conversations, so customer
  dedup correctly recognizes a repeat customer. Harness artifact, not a product bug.
- U002 (Thermia, general mode): bot suggested an extract-air-filter check for a ground
  source unit — generic-but-safe check in general mode; imprecise, never unsafe. Expected
  to improve once the FAQ corpus is approved.

---

## 5. Honest gaps (NOT yet validated)

- **FAQ-approved behavior**: every eval/e2e run so far exercises the UNAPPROVED corpus
  (retrieval sees nothing). What the general specialist does once the owner approves the
  102 entries — answer quality, staining/regeneration guidance, reduced escalation rate —
  is completely unvalidated.
- **Service-area gating live**: GeoSettings.enabled=False everywhere; the reject/border
  paths are unit-tested (`test_p_service_area.py`) but never exercised live/e2e with the
  gate ON.
- **Voice app**: not touched by this validation at all.
- **v1 e2e suite (`test_browser.py`, 6 scenarios)**: not re-run in S7 (was green at S6);
  only the 4 new v2 scenarios were run against HEAD+fix.
- **Postfix dataset is mixed-version** (§2): ~54 records pre-v2 (`4b87654`), the rest v2
  (`72e147c`) — and records after ~17:45 include the uncommitted postcode-early fix.
  Segmented reporting mitigates but does not remove this.
- **Judge is Gemini Flash on the same quota** — rubric dimension scores carry the usual
  LLM-judge noise; the hard metrics (false-resolution, DIY leak) are deterministic and
  quota-independent.
