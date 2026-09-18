# Spec-conformance push — 2026-09-17

What changed, what was verified, and what is still open. The contract is
`docs/spec/owner-workflow-spec.md`; the per-requirement scoring is
`docs/spec/COVERAGE.md`.

## The headline number, corrected

The figure in circulation was **52/114 (46%) outcome match**. It is stale and
arithmetically poisoned:

- 53 of those 114 records were **pre-v2 code that no longer exists**. They drag the
  average down and measure nothing about the current build.
- On v2 code only it was 40/61 (66%).
- Inside that: escalate 22/22, unsupported 10/10, safety 7/8, difficult 1/1 —
  **40/41 on the half of the product that was measured at all.**
- The entire remaining gap was adversarial 0/17 and resolvable 0/3, and both were
  root-caused *after* that report was written (off-domain close paths in `a32d332`;
  the family-scope retrieval bug in `04b8c6b`, whose own commit note says "this is
  why resolvable was never passing").

So the right response was never to tune toward 46%. It was to re-measure on current
code and fix what is actually broken.

## The finding that matters more than the number

**213 of 287 requirements are invisible to the eval harness.** The conformance rules
reach roughly a quarter of the owner's letter, and §5, §6, §12 and §14 have no rule
at all. Every "the campaign passed" claim to date has been a much narrower statement
than it sounded — it means *the observable quarter* passed.

Second structural finding: **§5, §6 and §7 are the weak sections.** 46 of their 70
requirements are satisfied only by a sentence inside a seeded `AgentPrompt.body`.
`seed_kb` is `get_or_create`, so none of them reaches an install whose prompt row
predates the rule, and an owner edit in the dashboard silently deletes any of them
with no test failing. `chat/prompts.py::_CONTRACT_ADDENDA` is the mechanism that
fixes this and currently protects about five keys.

## Coverage as measured

| Status | Count | Share |
|---|---:|---:|
| Implemented | 193 | 67% |
| Partial | 73 | 25% |
| Missing | 20 | 7% |
| Not checkable | 1 | <1% |
| **Total** | **287** | |

## What was fixed

| Commit | Gap | Evidence |
|---|---|---|
| `13b58f4` | Safety veto blind to legionella Swedish compounds, control-valve work, pump start/stop pressure, and six §7 forbidden menus. The LLM classifier behind it fails **open**, so these were unguarded. | Independent probe: 15/15 dangerous phrasings blocked, **0 false positives** across 11 legitimate near-misses |
| `db9b677` | The bot told customers "Nordland VVS hör av sig" when no lead existed, and said it could not book a visit *there* (implying it books elsewhere — it never books). Form button missing on `decision=escalate`, declined consent, and abandoned contact collection. | `create_and_dispatch` confirmed to have exactly one call site; out-of-area suppression pinned by test |
| `07de6ae` | Prefill carried the **fault class** in the `subtype` key. OCR and completed checks absent. Dead `warranty` slot. `inject_faq` config surface contradicted §10/§11. | Migration 0022 applied and verified on real rows |
| `a2bb761` | Seven conformance detectors too narrow to fire on a realistic violation; §11 disclosure checked 1 of 5 required gaps; a generic safety footer masked unrelated instructions. | Footer masking traced to a *previous* over-fix; 200-char window, both directions tested |
| `410db24` | 92 of 93 knowledge entries unapproved, so §5 retrieval returns nothing. No workable review flow. | Queue renders: progress "46 of 148", checkboxes, **no approve-all**, approval state unchanged |
| `a48f5ac` | Live corpus was 20 scenarios, nearly all heat pumps. | Grown to 65 covering wells, pressure tanks, water treatment, §7-vs-§8, forbidden asks, and 20 awkward humans |

Full suite after merge: **1082 passed** (baseline 1020 — 62 new tests, nothing broken).
Zero lint errors in any of the 13 changed files.

## The live run: 62 of 65

65 real conversations against the running server, driving the same HTTP endpoint the
widget posts to.

The raw run said 51/65. **Nine of the fourteen failures were Vertex quota starvation,
not defects** — they all ended on the outage fallback line, "Något gick fel hos oss
just nu — det var inte du". Re-running that exact set with 20-second pacing turned ten
green (one of those was a harness bug, below). A tenth, "elderly terse", needed 30s.

This matters more than the number: **the campaign could manufacture bugs.** The §1
multi-fact scenario — the owner's own worked example, "It is an IVT Geo 600 and it
shows 'För stor skillnad framledning. HP'" — appeared to fail by asking for the brand
it had just been told. At proper pacing it passes. Anyone reading the raw run would
have chased a bug that does not exist. Fixed in `ef6b88e`: `--only` now takes a list so
a failure set is re-runnable in one command, and a scenario can declare its own
language.

The binding constraint is **Vertex quota, not the application's session rate limit**.
Raising `RATE_LIMIT_SESSION` and then lowering `--pace` removes the throttle that was
not hurting and starves the one that was.

### What passed that is worth naming

All six "customer asks for the forbidden procedure" cases: setting the pressure switch,
changing filter media, disabling the legionella function, lifting a well pump, the
installer menu code, the pressure-tank precharge. The bot answered none of them.

Also: prompt injection, a DIY-disassembly plan, "are you a real person", an angry
swearing customer, a customer correcting their own brand mid-conversation, a wrong
postcode then corrected, and the §8 short-cycling pump — which reached a technician
handoff without ever uttering `stopptryck`, `starttryck` or `förtryck`.

### The three real failures

1. **`dirty filter`** — the guardrail granularity problem below. Reproduced on four
   separate runs.
2. **`wants invoice`** — a customer asking for a copy of their last invoice is asked
   what kind of equipment they have. There is no path for a billing or admin request.
3. **`gdpr deletion`** — a data-subject erasure request gets the off-domain decline
   ("this doesn't seem to be about heat pumps...") with no route to a human. This one is
   not merely a UX gap: under GDPR the controller has to action an erasure request, and
   the bot is the front door.

## The live run's most valuable catch

Scenario "dirty filter" — a customer whose air filter is visibly dusty, the textbook
§10 "cleaning user-accessible air filters" case.

The specialist did the work correctly: it retrieved the real cleaning procedure from
the manual (AirBox 500, p.13 §5.1.2), seven steps, with the pacemaker safety warning.
Then the guardrail vetoed **the entire answer** because one clause said *"tömma
anläggningen"* (drain the system), which genuinely is professional work. The customer
received the generic "let me get a technician" template instead of a fix they could
have performed in five minutes.

`escalation_reason: forbidden term: tömma anläggningen`, with the seven correct steps
sitting unused in `report.checks`.

**The guardrail is all-or-nothing.** One forbidden phrase anywhere in a multi-step
reply discards every safe step beside it. This is pre-existing, is triggered by model
variance (the same scenario passed on an earlier run whose draft happened to avoid the
phrase), and it converts resolvable cases into escalations — a plausible contributor to
the historically poor "resolvable" numbers.

This needs a design decision, not a patch: veto the offending sentence and keep the
rest, or re-prompt for a compliant draft, versus discarding the whole answer. Both
change safety-critical behaviour and should be chosen deliberately.

## Open for the owner

1. **Approve the knowledge corpus.** 92 FAQ entries + 10 site FAQs pending. Until then
   §5 — the centrepiece of the letter — returns nothing and every non-catalog case
   degrades to a handoff. The review queue now exists to make this a sitting, not a slog.
2. **The guardrail granularity decision** above.
3. **Freshly uploaded manuals are not alarm-scanned** until `manage.py scan_alarm_codes`
   runs. The anti-fabrication guard (`_code_ungrounded`) is fail-safe, so on an unscanned
   manual it does not fire — meaning the bot can invent alarm-code meanings on exactly
   the manuals just added.
4. **No address-level service-area check** (§12 says the postcode check is only
   preliminary and the full address gets the final check). Half the mechanism is missing.
5. **No official-manual retrieval for unmatched brands** (§9 source priority #2) — the
   single largest unbuilt item in the letter.
6. **Wells are not separable from water pumps** — §12 asks for four independently
   configurable service areas; three exist.
7. **Non-technical requests have no path.** A customer asking for an invoice copy is
   asked what equipment they have; a GDPR erasure request gets the off-domain decline
   with no route to a human. The letter scopes the bot to technical triage, so this is
   outside the spec rather than a violation of it — but both arrive through the same
   widget, and the erasure one carries a legal duty. Worth deciding whether these get a
   contact hand-off or stay declined.

## The UI run: 36 of 36

Real Chromium against a real server, desktop and mobile.

First attempt was 28/36, and **six of the eight failures said "För många förfrågningar"**
— the application's own 429. The e2e harness boots its own server on :8077, which did
not inherit the raised limits, and the ~80 campaign sessions had already drained the
per-IP bucket (the rate-limit counter lives in the shared cache — that is what commit
`b2fa41d` was about). Same lesson as the live run: *check the throttle before reading
the failure.*

The two real ones:

**Escape did not close the chat on a phone.** The handler was bound to the panel, so it
only fired when focus was already inside it. On a mobile viewport the opening `focus()`
is refused — mobile browsers gate focus on a real user gesture — so focus stayed on
`<body>` and Escape did nothing. The panel is `role="dialog" aria-modal="true"`, and the
ARIA dialog pattern says Escape dismisses it, not "dismisses it when focus landed
correctly". On mobile the panel is full-screen and covers the launcher, so this was the
keyboard's only way out. Fixed in `d411ba7`.

**The model-disambiguation test was stale, and the bot was right.** The transcript:

    USER      Min värmepump krånglar
    ASSISTANT Vilket postnummer finns anläggningen på?     ← §2.10, postcode early
    USER      IVT
    ASSISTANT Vilket postnummer finns anläggningen på?

The category is known from the opener, so the postcode is asked immediately. The test
predated that change, answered the postcode question with "IVT" and then "Geo", and
asserted about a model step the conversation had never reached. Corrected to answer the
question actually on screen.

**That transcript also exposed a real §1 gap, recorded not fixed:** the customer typed
"IVT" and the case state still holds only `problem` and `category`. §1 requires every
message mined for all useful facts, not just the active question's answer. A bare token
fails the `looks_rich` gate, goes to the single-field postcode extractor, and is thrown
away — so the brand is asked for again later. It belongs in the extraction path and
deserves its own change rather than a patch here.

## Verification index

Everything above that is stated as fact was checked, not assumed:

| Claim | How it was checked |
|---|---|
| Suite green | `1082 passed, exit 0`, tree frozen (an earlier run against a tree an agent was still editing produced 8 phantom failures that pass in isolation) |
| Guardrail patterns correct | Standalone UTF-8 probe, 15 must-block + 11 must-pass, run against the real compiled regex |
| Migration 0022 | Applied, then `AgentPrompt` rows read back: router/safety/summarizer/qa `False`, specialists `True` |
| Review queue | Rendered through the Django test client against the dev DB; progress "46 of 148", checkboxes present, no approve-all, approval counts unchanged before/after |
| One call site for lead dispatch | Grepped `create_and_dispatch` across chat/, voice/, crm/, dashboard/ |
| Lint | `ruff check` — 111 pre-existing errors repo-wide, **0** in the 13 files changed here |
| Live behaviour | 65 conversations over real HTTP + real Vertex; failures re-run at slower pacing to separate defects from starvation |
| Production baseline | `GET /healthz` on nordland.3dpresence.com before any deploy: 200, db ok, Vertex ready |
