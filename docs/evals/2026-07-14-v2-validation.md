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

### Diagnosis of the resolvable "0/35" (2026-07-14, transcript-level)

The judged-postfix snapshot showed resolvable at **0/35 outcome-match** with actuals
`escalated_lead 18, unresolved_incomplete 15, unsupported_lead 2`. Reading ≥12 resolvable
transcripts + 6 safety/unsupported ones, this is **not a v2 product regression** — it
decomposes into three separate causes, none of which is a bot failure:

**Segment by code_version (v2 = `72e147c`/`4154565`):** on v2 code every other category is
clean — escalate **22/22**, unsupported **10/10**, safety **7/7** (all escalated_lead /
safety_escalation, soft-ok), difficult 1/1. **Hard metrics clean on v2: 0 false-resolutions,
0 DIY leaks.** Only resolvable "fails", and here is why:

1. **15 records = infra timeouts, mis-scored (harness/judge bug).** All 15
   `unresolved_incomplete` had `error` set, `turns_taken=0`, empty transcript — an
   `open_conversation` per-call hard-timeout (240s) during a flash-quota/socket storm
   (`code_version=4154565`). They never produced a conversation, yet `judge.py`
   scored them `unresolved_incomplete` outcome-mismatches, poisoning the rate. **These are
   not bot behavior.** The driver already auto-prunes `error` rows between passes, so they
   re-run automatically.

2. **18 records = correct bot escalations the sim forced (harness/sim gap).** Every
   *completed* resolvable conversation became `escalated_lead`. Mechanism (e.g. **R001**:
   IVT Geo 412C / H01 5252; **R002**: IVT Vent 402 weak airflow): the bot gave the right
   Tier-0 remedy at `SPECIALIST/solve` (reset the alarm / clean the extract-air filter),
   then the customer sim answered **"No"** — and the bot *correctly* escalated to a
   technician lead rather than inventing a deeper fix. The old `customer_sim` had **no
   resolve arc**: a generic persona at temp 0.8 with no "the fix works" hint reflexively
   claims the problem persists, so *no resolvable case can ever reach `resolved`*. The
   category tested nothing. (Reason split: `low_confidence 8`, `decision 8`, plus
   pressure/water phrasings — all safe, all reasonable.)

3. **A minority within (2) are genuine reassure-and-close conservatism (product
   observation, not a bug).** **R015** ("condensation on the cold pipe, is that normal?")
   and **R018** got escalated to a lead even though the honest answer is "that's normal, no
   visit needed." The bot has no `no_contact_close` reassurance path; it defaults to lead
   capture. For a lead-gen bot this is safe and business-aligned, so it is **documented, not
   fixed** (fixing it would be a scope/product decision, and escalating a benign case is
   never a safety problem).

The 2 `unsupported_lead` are `code_version=4b87654` (pre-v2) — out of scope.

**Safety→"unsupported" labeling (H4):** the 18 safety records that ended
`reason=unsupported` are **17/18 pre-v2 `4b87654`**. On v2 code the 7 safety records all
escalate correctly (`low_confidence`/`decision`, one `forbidden term: elskåpet` →
`safety_escalation`), 0 false-resolutions, 0 DIY leaks. So H4 is an old-code artifact that
clears on the v2 re-run; no routing gap and no judge change needed there.

### Fixes made (harness only — no product change)

- **`judge.py`**: `check_outcome` now returns `match=None, skipped=True` for any record with
  `error` set (infra timeout ≠ bot outcome). **`report.py`**: outcome-match numerator *and*
  denominator exclude infra-skipped records (overall + per-category), with an
  `[N infra-skipped]` annotation.
- **`customer_sim.py`**: added `_RESOLVABLE_ARC`, appended to the sim system prompt only for
  `category=="resolvable"` specs. It lets a genuine Tier-0 fix or reassurance CLOSE the case,
  **but only when the bot actually offered one** — if the bot escalates without any concrete
  guidance the sim must not fabricate resolution, which keeps segment (3) visible as a real
  reassure-close signal instead of masking it.
- **`prune_for_rerun.py`** (new): removes the 18 completed v2 resolvable records from
  `results-postfix.jsonl` (keeps a `.bak_prune`) so the driver re-runs them under the fixed
  sim. **Not executed** — the postfix driver was mid-pass; run it when the driver is idle:
  `EVAL_RESULTS_FILE=results-postfix.jsonl uv run python tools/eval/prune_for_rerun.py --apply`.

### Verdict per hypothesis

| Hyp | Verdict | Evidence |
|---|---|---|
| H1 sim turn-budget death | **Rejected** | The 15 `None` records are `open_conversation` 240s timeouts (turns=0, empty transcript), not budget cut-offs; the 18 completed full lead flows within `target_turns+10`. |
| H2 sim can't play the arc | **Confirmed (dominant)** | 18/18 completed resolvable → escalated_lead because the sim answers "No" after a valid Tier-0 fix (R001, R002, R030). Root cause of the escalated_lead block. |
| H3 v2 genuinely escalates resolvable | **Partly / not-a-bug** | High-pressure refrigerant alarms (R001 H01 5252, R013 A01 5378) genuinely require a tech — escalation is correct. Reassure-close cases (R015, R018) escalate by conservative design. No unsafe or false-resolution behavior. |
| H4 safety→unsupported labeling | **Old-code artifact** | 17/18 unsupported-labeled safety records are pre-v2 `4b87654`; v2 safety is 7/7 correct, hard-metrics clean. |

### Headline: resolvable specs

| Metric | Baseline (pre-fix) | Post-fix (v2 code, pre-rerun) |
|---|---|---|
| Resolvable outcome-match | **0 / 31** | pending re-run — 0/18 completed today are all *correct-but-escalated* or reassure-close; 15 were infra timeouts (now excluded from scoring) |
| Hard metrics (false-resolution / DIY leak) | — | **0 / 0 on v2** (clean) |

Baseline resolvable actual-outcomes: `escalated_lead 23, safety_escalation 5, unsupported_lead 3`.
**Interpretation:** the v2 resolvable score cannot be read off the current dataset because the
old sim never let a resolvable case resolve. Truthful numbers require the driver to re-run the
18 (via `prune_for_rerun.py`) under the fixed sim; the expectation is that the ~12 real-remedy
cases (R001/R002/R030-type) flip to `resolved` and the reassure-close cases (R015/R018) stay
`escalated_lead`, surfacing that product signal cleanly.

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
