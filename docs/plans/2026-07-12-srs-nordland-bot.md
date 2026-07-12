# Software Requirements Specification — Nordland VVS Support Bot Expansion

Date: 2026-07-12. Status: DRAFT for review. Planning artifact only — no source
code is changed by this document.

Grounding: every requirement below is traceable to one of two read-only audits,
cited inline as `[AUDIT-CS §n]` (`docs/plans/2026-07-12-audit-current-state.md`)
or `[AUDIT-VR §n]` (`docs/plans/2026-07-12-audit-budtender-voice-reuse.md`), or to
a source path verified during authoring. Where an audit flags a hard constraint
(WSGI-not-ASGI, fake SSE streaming, async-lead-only escalation, EU data residency,
no webhook auth), the requirement either respects it or explicitly calls for
changing it. No requirement hand-waves past a flagged constraint.

Scope of this SRS: the six net-new capabilities the owner asked for —
(1) cloned Nordland homepage with the widget embedded, (2) widget voice mode via
ElevenLabs, (3) photo upload in all channels, (4) phone channel via Vapi + n8n
with WhatsApp photo ingestion visible mid-call, (5) all new configuration in the
existing admin dashboard, (6) a robust conversation test suite (specified in a
separate doc, referenced here only). The existing web chat is documented as the
frozen baseline everything else must preserve.

---

## Table of contents

1. Purpose & product vision
2. Bot capability scope definition (the centerpiece)
3. User classes & personas
4. Functional requirements (FR-x)
5. Non-functional requirements (NFR-x)
6. External interfaces
7. Acceptance criteria per FR
8. Traceability appendix (FR → code)

---

## 1. Purpose & product vision

### 1.1 The product in one sentence

Nordland VVS's support bot is a **triage nurse, not a surgeon**: across web chat,
web voice, and phone, it confidently answers very low-stakes questions, resolves a
short list of trivially-simple self-service fixes, gathers excellent structured
context on everything else, and hands a clean, complete case to a human specialist
— never guessing at a hard diagnosis, never instructing dangerous work.

### 1.2 What "triage nurse, not surgeon" means precisely

The bot's job is **not** to be right about hard heat-pump faults. Its job is to be
*confidently right about the easy things, honestly fast about the boundary, and
excellent at intake*. Concretely, three jobs in priority order:

1. **Deflect the trivial with confidence.** A dirty filter, a machine that needs a
   restart, a thermostat/mode setting, a summer/winter switch, a tripped-and-
   resettable info alarm that clears itself — the bot resolves these end-to-end
   without a human, because the existing KB already contains this material
   (`geo_troubleshooting.txt`, `geo_perceivable_errors.txt`, `vent_maintenance_full.txt`,
   `case1_geo_filter.txt`, `case2_geo_thermostat.txt`, `case3_vent_filter.txt` at
   repo root — Swedish maintenance/troubleshooting text for IVT Geo, Bosch Greenline,
   IVT Vent 402) `[AUDIT-CS §7]`. The audit records this class was explicitly lifted
   from "0% → ~80%" resolution in commit `75906aa` — that is the target class, not
   a stretch goal.

2. **Gather excellent structured context.** For anything past trivial, the bot's
   deliverable is a *complete case*: machine identity (brand / model / serial /
   error code, from text or a nameplate photo), symptom description, photos of the
   fault, and contact info — assembled deterministically into `crm.Session` and
   dispatched as a `crm.ServiceRequest` lead so the human specialist opens the case
   already knowing everything `[AUDIT-CS §1, §3, §4]`. Intake quality *is* the
   product for the non-trivial majority.

3. **Recognize out-of-scope fast, and refer — don't guess.** Unsupported brand,
   ambiguous fault, anything the confidence gate rejects, anything the safety layer
   vetoes → the bot stops trying to solve, collects contact info, and creates a
   lead / schedules a callback. The existing three-trigger escalation already does
   exactly this `[AUDIT-CS §4]`; the new channels must preserve it.

### 1.3 Why the existing architecture already fits this vision

The chat pipeline is a **deterministic, code-owned finite-state machine**
(`chat/orchestrator.py`); the LLM is called per-step but never controls state
transitions `[AUDIT-CS §1]`. Confidence gating (`CONFIDENCE_GATE = 0.70`,
`chat/orchestrator.py:33`), a two-layer safety guardrail (hardcoded keyword veto +
LLM classifier, `chat/guardrails.py`), and a reply-budget ceiling
(`REPLY_BUDGET = 5`, `chat/orchestrator.py:34`) are the machinery that already
enforces "don't guess past your competence." The expansion's job is to extend this
same brain to new front-doors — **not** to build a smarter brain. Every new channel
funnels into the same orchestrator, the same KB, the same guardrails, the same lead
pipeline `[AUDIT-VR §4 "one dispatch() layer, multiple front-doors"]`.

### 1.4 Vision-level non-negotiables

- The FSM stays code-owned. New channels are new transports, not new decision logic.
- Safety guardrails are baseline-hardcoded and ADD-ONLY from the dashboard
  `[AUDIT-CS §1]` — no channel may weaken them.
- EU data residency posture (`config/settings.py:162`, fail-closed to `europe-*`
  unless `ALLOW_NON_EU_RESIDENCY=1`) governs every new AI vendor choice, not just
  Gemini `[AUDIT-CS §3, §9, gotcha 7]`.
- "Escalation" means *async lead today*; live human transfer is a **new** capability
  for phone only, explicitly scoped (see FR-PHN and §2.5) `[AUDIT-CS §4]`.

---

## 2. Bot capability scope definition (CENTERPIECE)

This section defines a precise, testable boundary for what the bot may attempt.
It is the contract the conversation test suite (item 4, separate doc) asserts
against. Four confidence tiers, a per-brand policy, hard safety rules, and explicit
non-goals.

### 2.1 Confidence tiers per problem type

Every inbound problem resolves into exactly one of four tiers. The tier determines
the bot's allowed behavior. Tiers map onto machinery that already exists in
`chat/orchestrator.py`.

#### Tier 0 — RESOLVE AUTONOMOUSLY (deflect, no human)

- **Definition**: low-stakes, self-service, documented-in-KB fixes the customer can
  safely perform with no tools and no risk. The canonical set (from the seeded
  content): dirty/clogged filter cleaning behind a front cover, power-cycle/restart,
  thermostat or operating-mode setting, summer/winter or holiday-mode toggle,
  reading/clearing a self-clearing information alarm, checking a tripped RCD the
  customer can see (observe only — see safety rules), confirming a closed shutoff
  valve state.
- **Allowed behavior**: the specialist agent answers directly and marks
  `decision = "solve"`; the turn resolves when `confidence >= CONFIDENCE_GATE (0.70)`
  and the guardrail passes and `in_docs` is true `[AUDIT-CS §1 SPECIALIST]`.
- **Gate**: answer must be grounded in an actual `MachineDocument` / `GenericGuide`
  / `FAQEntry` for the identified machine (or a category best-practice guide). A
  Tier-0 answer that is *not* in-docs is downgraded to Tier 1 (the code already caps
  confidence when the model flags `in_docs:false` or the machine match is weak <0.4)
  `[AUDIT-CS §1]`.
- **Example**: "IVT Vent 402, it's noisy and airflow dropped" → filter guidance from
  `case3_vent_filter.txt` → resolved.

#### Tier 1 — TROUBLESHOOT THEN ESCALATE (attempt, bounded, then hand off)

- **Definition**: a problem that is plausibly simple but not certain; the bot may
  ask up to a bounded number of diagnostic questions and offer documented first
  steps, but must escalate the moment it exhausts its budget or drops below the
  confidence gate.
- **Allowed behavior**: the specialist loop runs, capped at `REPLY_BUDGET = 5`
  specialist turns (`chat/orchestrator.py:34,331`). Any of {`confidence < 0.70`,
  `decision != "solve"`, budget exhausted, guardrail unsafe} → `STATE_ESCALATE`
  with a typed `escalation_reason` (`low_confidence | budget | decision | <safety>`)
  `[AUDIT-CS §1, §4; chat/orchestrator.py:380-385]`.
- **Gate**: the bot must never present a Tier-1 attempt as a confirmed fix. If it
  escalates, the partial troubleshooting is captured in
  `Session.troubleshooting_performed` (JSON list) so the specialist sees what was
  already tried `[AUDIT-CS §3]`.
- **Example**: "Greenline HE, alarm keeps coming back after I reset it" → two
  documented checks → still failing → escalate with full context.

#### Tier 2 — INFO-GATHER ONLY (no diagnosis attempted)

- **Definition**: equipment/brand the bot has no manual for, or a fault class the
  policy marks referral-only, or an unsupported category. The bot must **not**
  attempt a fix at all — only collect a complete, qualified lead.
- **Allowed behavior**: `STATE_UNSUPPORTED_INTAKE` → the `intelligent_intake` agent
  gathers machine identity + symptom + photos + contact and **always** escalates
  (`escalation_reason = "unsupported"`) `[AUDIT-CS §1 UNSUPPORTED, §4]`. Also reached
  by a `RoutingRule` override (`route_maintenance` / `urgent_contact`) that skips the
  specialist entirely `[AUDIT-CS §1 ROUTING, §2]`.
- **Gate**: no troubleshooting text is emitted. The bot may confirm the brand is one
  Nordland services (to set expectations) but offers no diagnostic steps.
- **Example**: a brand with a `Machine` row but no `MachineDocument` (brand chip
  shown so the customer can pick it, but it still escalates) `[AUDIT-CS §5]`.

#### Tier 3 — REFUSE + SAFETY ESCALATE (decline the task, warn, hand off)

- **Definition**: anything the hard safety rules (§2.3) cover — water leaks,
  electrical/wiring, refrigerant, gas/combustion, pressure systems, legionella,
  deep disassembly. The bot must refuse to give DIY instructions, deliver a brief
  safety message, and escalate immediately.
- **Allowed behavior**: the keyword veto (`chat/guardrails.py::_FORBIDDEN`) and/or
  the LLM safety classifier force `STATE_ESCALATE` regardless of confidence or DB
  config `[AUDIT-CS §1 guardrails]`. No troubleshooting steps are emitted for the
  vetoed action.
- **Gate**: refusal is mandatory and cannot be configured away from the dashboard
  (guardrails are ADD-ONLY). For an active hazard (gas smell, active water leak,
  burning smell), the message must include an urgent real-world instruction (shut
  off / call emergency services / call Nordland's urgent line) — NOT a DIY repair
  step.
- **Example**: "how do I re-gas the refrigerant" → refuse, urgent-referral, escalate.

**Tier resolution is deterministic and code-owned.** Tier is not an LLM free choice:
Tier 3 is forced by the guardrail layer; Tier 2 by machine-identification failure or
a `RoutingRule`; Tier 0/1 split by the specialist confidence gate. This is why the
tiers are testable — each has a code-observable trigger `[AUDIT-CS §1, §4]`.

### 2.2 Per-brand policy (grounded in the seeded catalog)

Seeded vendors (`kb/management/commands/seed_kb.py::VENDORS`) `[AUDIT-CS §7]`:
`IVT, Bosch, Grundfos, Debe, Scandia Pumps, Aqua Expert, Aqua Invent`.

Policy is driven by **whether a `MachineDocument` manual exists for the identified
machine**, not by brand name alone — the router/specialist path engages only when
`kb.identification.identify_machine()` returns a `Machine` *and* that machine has
usable docs; otherwise the flow drops to Tier 2 `[AUDIT-CS §1, §2]`. The table
below states the *intended* policy per brand given current seed content; the actual
runtime behavior always defers to "is there a manual for this exact model."

| Brand | Category | Seed machines / content | Confidence policy | Max tier the bot may attempt |
|---|---|---|---|---|
| **IVT** | Heat pump (exhaust-air, ground-source) | IVT 490, IVT 402 seeded; loose content for IVT Geo 412C, Vent 402 `[AUDIT-CS §7]` | **Supported** for models with a `MachineDocument`; discuss with confidence | Tier 0/1 |
| **Bosch** | Heat pump (air-to-water, ground-source) | Bosch Compress 7000i seeded; Greenline HE/HEC-E content present `[AUDIT-CS §7]` | **Supported** for models with docs | Tier 0/1 |
| **Grundfos** | Water pump / well | Grundfos SQ seeded `[AUDIT-CS §2]` | **Supported** for seeded pump models; simple checks only | Tier 0/1, conservative |
| **Debe** | Water pump / well | Debe DPM seeded `[AUDIT-CS §2]` | **Supported** for seeded models | Tier 0/1, conservative |
| **Scandia Pumps** | Water filtration | Vendor seeded, **no seed machine/doc** `[AUDIT-CS §2, §7]` | **Info-gather only** until docs loaded | Tier 2 |
| **Aqua Expert** | Water filtration | Vendor seeded, **no seed machine/doc** | **Info-gather only** until docs loaded | Tier 2 |
| **Aqua Invent** | Water filtration | Vendor seeded, **no seed machine/doc** | **Info-gather only** until docs loaded | Tier 2 |
| *Any unlisted brand* | — | brand can be typed free-text | **Info-gather only**, always lead | Tier 2 |

Notes binding on requirements:

- **Brand chips ≠ supported-for-troubleshooting.** Widget brand chips are "brands we
  service in this category" (IVT+Bosch for heat), scoped to any `Machine` row, not
  filtered to only-manualed machines — so an unlisted or under-documented brand can
  still be picked and correctly escalates to a lead `[AUDIT-CS §5]`. The per-brand
  policy above must not be conflated with chip visibility.
- **The loose `.txt` content is not yet loaded as `MachineDocument` rows** for
  Geo 412C / Greenline HEC-E / Vent 402 exact models `[AUDIT-CS §7]`. Until it is,
  those models may fall to Tier 2 at runtime even though the brand is "supported."
  FR-KB-1 calls for confirming/loading this content so the Tier-0 deflection target
  is actually reachable in production (also check `nordland.sql`, the unexamined
  prod dump, which likely holds real KB content `[AUDIT-CS §7, gotcha 13]`).
- **Water-filtration brands (Scandia/Aqua Expert/Aqua Invent) are info-gather-only
  by default** because no manuals are seeded. The dashboard must let staff promote a
  brand to "supported" by uploading manuals (FR-KB-1) — the policy is data-driven,
  not hardcoded.

### 2.3 Hard safety rules (non-negotiable, all channels)

These are enforced in code regardless of DB/prompt config and cannot be weakened
from the dashboard (`chat/guardrails.py`, `_BASELINE_GUARDRAILS` shown read-only in
the dashboard) `[AUDIT-CS §1, §6]`. They apply identically to web chat, web voice,
phone, and WhatsApp.

**S-1 — Electrical.** No instructions for wiring, fuse boxes, mains, control/service
panels, or anything behind a dangerous panel. (A plain filter-cover front panel is
explicitly *not* vetoed, so Tier-0 filter cleaning stays allowed — the regex is
tuned for exactly this distinction `[AUDIT-CS §1]`.) Any electrical-work request →
Tier 3.

**S-2 — Refrigerant.** No instructions to open, charge, recover, or work on the
refrigerant circuit. → Tier 3.

**S-3 — Gas / combustion / flue.** No DIY on gas, combustion, or flue work. An active
gas smell → urgent real-world safety instruction + immediate escalation, never a
repair step. → Tier 3.

**S-4 — Water leaks / pressure systems.** No DIY on pressurized water systems; an
*active* leak → advise shutting the stopcock / powering down if safe + urgent
referral, not a repair procedure. → Tier 3.

**S-5 — Legionella / water treatment.** No legionella treatment instructions. → Tier 3.

**S-6 — Deep disassembly.** No instructions requiring opening the sealed machine
body beyond documented user-serviceable covers. → Tier 3.

**S-7 — Output-leak / prompt-injection.** Echoed trust-boundary delimiters or
"system prompt"/"these instructions" leakage forces escalation (`_LEAK` regex)
`[AUDIT-CS §1]`. Customer-supplied text is always spotlight-wrapped as untrusted
DATA (`chat/sanitize.py::wrap_untrusted`) `[AUDIT-CS §1]` — this must hold for
voice-transcribed text and WhatsApp text too (FR-STT-3, FR-WA-4).

**S-8 — Two-layer enforcement.** Keyword veto is the hard gate; the LLM classifier
is a second opinion; any hit forces `STATE_ESCALATE` `[AUDIT-CS §1]`. Voice and
phone channels must run the **same** `guardrails.is_unsafe()` on the drafted reply
*before* it is spoken (FR-STT-3, FR-PHN-4) — TTS must never voice an unvetted draft.

### 2.4 Explicit non-goals

- **Not a diagnostic expert system.** The bot does not attempt root-cause diagnosis
  of hard faults. Past Tier 1 it gathers and refers `[vision §1.2]`.
- **Not a scheduler/booking engine.** The bot captures a lead and (phone) can offer
  a callback; it does not write to a calendar or commit an appointment slot. Booking
  intent is captured (`Session.booking_requested`) for a human `[AUDIT-CS §3]`.
- **Not a quote/pricing tool.** No prices, no quotes; `PolicyDocument`s are cited at
  booking/quote/maintenance time only, never injected into troubleshooting
  `[AUDIT-CS §2]`.
- **Not a live human chat on web.** Web chat/voice "escalation" is an async lead, not
  a live handoff `[AUDIT-CS §4]`. Live transfer exists only on the phone channel and
  only where FR-PHN-5 provides it.
- **Not a general-purpose assistant.** Off-domain questions (not HVAC/VVS/water) are
  politely declined and, if a service need is implied, converted to a lead.
- **No autonomous financial or account actions** (payments, account changes) — out of
  scope by product and by the assistant's own safety rules.
- **Not multilingual beyond sv/en.** Swedish and English only (`LANG_CHOICES`)
  `[AUDIT-CS §1 i18n]`. Other languages are a future concern.

### 2.5 Escalation semantics per channel (the load-bearing distinction)

| Channel | "Escalation" means | Live human transfer? |
|---|---|---|
| Web chat | Create `ServiceRequest` async lead `[AUDIT-CS §4]` | No |
| Web voice | Same async lead (identical FSM) | No |
| Phone (Vapi) | Async lead **and/or** offer callback; optionally warm-transfer to a human line if configured (FR-PHN-5) | **New capability** — must be built, not reused `[AUDIT-CS §4]` |
| WhatsApp | Async lead | No |

This table is the single most important planning fact: nothing today transfers a
conversation to a human in real time `[AUDIT-CS §4, gotcha 4]`. Web voice does not
change that. Only the phone channel may add warm transfer, and only as new code.

---

## 3. User classes & personas

### 3.1 Homeowner (primary, web + phone)

Owns a heat pump / well pump / water filter serviced by Nordland. Non-technical.
Wants the quickest path to either a fix or "someone is coming." May not know the
model number → nameplate-photo path is critical (`_run_vision`, FR-PHOTO)
`[AUDIT-CS §1]`. Swedish-first, some English. Reaches the bot via the website
widget or (new) the cloned homepage, or by phone.

### 3.2 Property manager (web, higher volume)

Manages multiple properties/units, may report several machines. Values structured
intake and a paper trail. The CRM-360 equipment history and returning-customer
detection (`phone_hash`) serve this persona well `[AUDIT-CS §3]`. Likely to reuse
the bot repeatedly → cross-channel identity join (FR-ID) matters most here.

### 3.3 Elderly caller (phone-first)

Prefers the phone, may struggle with a web widget entirely. Needs slow, clear,
patient turn-taking; short sentences; generous barge-in tolerance. The phone
channel's latency and turn-taking NFRs (NFR-LAT-3) exist largely for this persona.
May be guided over the phone to send a WhatsApp photo of the machine's nameplate —
the mid-call WhatsApp ingestion flow (FR-WA, FR-PHN-6) is designed so the agent can
say "I've received your photo, I'm looking at your IVT Greenline now" `[AUDIT-VR
Gaps §1, §2]`.

### 3.4 Swedish speaker (default) and English speaker

Swedish is the default (`data-lang="sv"` typical embed). Web users pick language
from the widget; **phone/voice users cannot pick from a dropdown** — language must
be detected from speech or set per phone number `[AUDIT-CS §1 i18n, gotcha 10]`.
Free-form LLM replies localize via a `{locale}` prompt directive; templated strings
via the in-code `T` dict; dashboard chrome via gettext `.po` — three separate
mechanisms the new channels must respect (FR-I18N) `[AUDIT-CS §1]`.

### 3.5 Staff operator (dashboard, internal)

Solo/small team, `@staff_member_required`, no role system `[AUDIT-CS §6]`. Configures
agents, KB, guardrails, and (new) channel/credential settings. Reviews sessions,
leads, and (new) calls. Needs zero-redeploy config changes and instant-but-safe
publish to Vapi (FR-DASH) `[AUDIT-VR §5]`.

---

## 4. Functional requirements

Grouped by area. Each FR has an ID, a statement, and a source. Acceptance criteria
are in §7 (same IDs). "Baseline" FRs describe existing behavior that must be
preserved; "new" FRs describe net capability.

### 4.0 Web chat — BASELINE (must be preserved unchanged)

- **FR-CHAT-1 (baseline).** The system shall expose `POST /api/chat/session` and
  `POST /api/chat/<public_id>/message` with the existing anonymous, `public_id`-
  bearer contract and SSE response frames `[AUDIT-CS §5]`.
- **FR-CHAT-2 (baseline).** The FSM (`INTAKE → ROUTING → SPECIALIST | UNSUPPORTED →
  ESCALATE → RESOLVED`) shall remain code-owned in `chat/orchestrator.py`; no new
  channel may relocate decision logic into config or the LLM `[AUDIT-CS §1]`.
- **FR-CHAT-3 (baseline).** Guardrails, sanitization, confidence gate, reply budget,
  and turn ceilings shall apply to every channel via the shared orchestrator
  `[AUDIT-CS §1]`.
- **FR-CHAT-4 (baseline).** Lead creation/dispatch (`crm.leads.create_and_dispatch`,
  idempotent per `(ServiceRequest, sink)`) shall remain the single escalation
  mechanism for web `[AUDIT-CS §3, §4]`.

### 4.1 Homepage clone + widget embed

- **FR-HOME-1 (new).** The system shall serve a static clone of the Nordland VVS
  homepage (referencing `nordlandvvs.se`, the real site — **not** the demo
  `nordland.3dpresence.com`) `[AUDIT-CS §7]`, with the existing widget embedded via
  a single `<script>` tag pointing at the Nordland backend origin. No widget code
  change is required — the script derives its API origin from its own `src`
  (`API = new URL(script.src).origin`) `[AUDIT-CS §5]`.
- **FR-HOME-2 (new).** The clone's origin shall be added to `WIDGET_ALLOWED_ORIGINS`
  (`config/settings.py:32`) so the hand-rolled CORS middleware
  (`core/middleware.py::WidgetCorsMiddleware`) admits it — this is the *only* backend
  change the clone requires `[AUDIT-CS §5, gotcha 11]`.
- **FR-HOME-3 (new).** The clone shall reproduce Nordland's homepage layout/branding
  faithfully enough to demo the widget in context (a marketing/demo surface), and
  shall be responsive and not degrade the widget's existing keyboard trap, reduced-
  motion, and language-switch behavior `[AUDIT-CS §5]`.
- **FR-HOME-4 (new).** The clone must contain no scraped copyrighted third-party
  assets beyond what Nordland owns/authorizes; asset provenance is a review gate
  before publish.

### 4.2 Widget voice mode (ElevenLabs)

- **FR-VOICE-1 (new).** The widget shall offer a voice mode toggle: the user speaks
  instead of typing, and the bot replies with synthesized speech, while **KB, FSM,
  guardrails, confidence gating, photo upload, and lead flow remain identical** to
  text chat `[owner intent; AUDIT-CS §1]`. Voice is a transport over the same
  `process_turn()`, not a new brain.
- **FR-VOICE-2 (new).** Speech-to-text shall convert the user's utterance to text
  that is fed to `process_turn(user_text=...)` exactly as typed text would be
  `[AUDIT-VR §4]`. The STT vendor choice must respect the EU-residency posture
  (§2, NFR-GDPR-2) or trigger an explicit non-EU acceptance decision.
- **FR-VOICE-3 (new).** Bot replies shall be synthesized via **ElevenLabs** TTS. The
  ElevenLabs API key, voice id, model, and voice settings shall be configured from
  the dashboard credentials surface, never hardcoded (FR-DASH-2) `[AUDIT-VR §2 P6,
  §5]`.
- **FR-VOICE-4 (new).** Because `process_turn()` computes the full reply before any
  SSE frame is emitted (no real LLM token streaming — the SSE "streaming" is a UX
  trick) `[AUDIT-CS §5, gotcha 2]`, the voice design shall EITHER (a) accept
  "wait for full text, then TTS" latency (default, simplest), OR (b) introduce
  genuine `gemini.generate_stream()` wiring in the specialist path — the latter is a
  nontrivial FSM refactor and is explicitly out of the default scope. The SRS
  requires (a) unless NFR-LAT-2 cannot be met, in which case (b) is the sanctioned
  fallback, not an ad-hoc hack.
- **FR-VOICE-5 (new).** Voice mode shall degrade gracefully to text: if mic
  permission is denied, STT fails, or TTS is unavailable, the widget falls back to
  the existing text UI with a visible notice; a conversation is never lost.
- **FR-VOICE-6 (new).** The drafted reply text shall pass `guardrails.is_unsafe()`
  before being sent to TTS; an unsafe/escalating turn is spoken as the escalation
  message, never as a vetoed troubleshooting step (§2.3 S-8).

### 4.3 Photo upload (all channels)

- **FR-PHOTO-1 (baseline).** Web chat photo upload shall continue to work via the
  existing multipart path on `POST /api/chat/<public_id>/message` (`image` field),
  through `sanitize_image()` (Pillow verify, JPEG/PNG/WEBP only, 8 MB cap,
  decompression-bomb guard, EXIF/GPS strip by re-encode) → `_run_vision()` (Gemini
  nameplate/error-code OCR) → `CaseState.slots` `[AUDIT-CS §1]`.
- **FR-PHOTO-2 (new).** Photo upload shall be available in **voice mode** (the widget
  keeps its attach control regardless of input mode) and route through the identical
  `sanitize_image()` → `_run_vision()` pipeline. The voice reply shall acknowledge a
  received photo ("I can see your nameplate…") `[owner intent].
- **FR-PHOTO-3 (new).** Photos arriving via WhatsApp (FR-WA) and via any async path
  shall funnel into the **same** `sanitize_image()` → `_run_vision()` → `CaseState`
  pipeline — the OCR/sanitization logic shall be reused, not duplicated
  `[AUDIT-CS gotcha 5]`. This requires factoring the ingestion so it is callable
  outside the synchronous chat-turn request cycle (see FR-WA-3).
- **FR-PHOTO-4 (baseline).** The per-conversation image quota
  (`MAX_IMAGES_PER_CONVERSATION`, default 8, `chat/views.py:85`) shall be enforced
  across all channels for a given conversation `[AUDIT-CS §1]`.
- **FR-PHOTO-5 (baseline).** On escalation, uploaded photos shall be copied to
  `crm.CustomerFile` (dedup by sha256) so they survive PII purge of the transcript
  `[AUDIT-CS §1, §3]`.
- **FR-PHOTO-6 (constraint).** Media storage is local disk (`MEDIA_ROOT =
  data/uploads`, bind-mounted); no S3/GCS abstraction exists `[AUDIT-CS gotcha 12]`.
  WhatsApp media URLs and any recordings shall be downloaded into this same local-
  disk model, OR a storage-backend change shall be an explicit, separately-scoped
  decision — not assumed.

### 4.4 Phone channel (Vapi)

- **FR-PHN-1 (new).** The system shall accept inbound phone calls via a Vapi
  assistant/squad, with a webhook receiver at a new Django URL behind the existing
  Caddy block (`nordland.3dpresence.com`, no separate ingress needed) `[AUDIT-CS §9;
  AUDIT-VR §1]`.
- **FR-PHN-2 (new).** The Vapi webhook shall be built as an in-process Django app
  (e.g. `voice/`) that calls `chat.orchestrator` / `crm` **directly via Python
  import**, not over an internal HTTP hop — swedish-bot is a single project, unlike
  the two-repo happytime source `[AUDIT-VR Risks "two-repo vs one-repo"]`.
- **FR-PHN-3 (new).** The webhook shall verify Vapi's signature FIRST and fail closed
  (HMAC `X-Vapi-Signature` or shared-secret `X-Vapi-Secret`, constant-time compare;
  an unconfigured secret rejects) before parsing any body — porting `voice/signing.py`
  near-verbatim `[AUDIT-VR §1]`. This is mandatory because the existing chat API has
  **no auth** and that trust model is wrong for a public webhook `[AUDIT-CS gotcha 6]`.
- **FR-PHN-4 (new).** Each phone turn shall route the transcribed utterance through
  the **same** orchestrator FSM, KB, guardrails, and confidence gate as web chat; the
  spoken reply is the orchestrator's drafted text, TTS'd by Vapi's configured voice
  (ElevenLabs), and only after passing `guardrails.is_unsafe()` `[AUDIT-VR §1, §4;
  §2.3 S-8]`.
- **FR-PHN-5 (new, live transfer).** For calls that hit Tier 2/3 or an
  `urgent_contact` RoutingRule, the assistant shall EITHER create an async lead +
  offer a callback, OR (if a human line is configured) warm-transfer the live call —
  this transfer is **net-new capability**, not a reuse of `_escalate_step`
  `[AUDIT-CS §4, gotcha 4]`. Warm transfer is optional/configurable; async-lead +
  callback is the mandatory floor.
- **FR-PHN-6 (new).** Everything-as-code provisioning: the Vapi assistant/squad shall
  be provisioned from DB rows (`AgentPrompt` + new voice/channel fields) via a
  reconcile-by-name-then-id engine with a sha256 zero-drift hash oracle (a re-run
  with no config change performs zero Vapi writes), shared between a CLI provisioner
  and the dashboard "Publish to Vapi" button `[AUDIT-VR §2]`.
- **FR-PHN-7 (new, durable log).** The end-of-call report shall write an idempotent
  durable call record FIRST (`update_or_create` by Vapi `call_id`), then classify the
  outcome deterministically in code (not by LLM), then do post-call summary/sink work
  — ADR-017 ordering `[AUDIT-VR §1, §4]`. Call records extend the existing CRM/idempotency
  idioms (`Session`/`ServiceRequest`/`LeadDelivery`) rather than a parallel model set
  `[AUDIT-VR §4]`.
- **FR-PHN-8 (constraint).** The WSGI/gunicorn deployment ties up a worker thread per
  open connection `[AUDIT-CS §9, gotcha 1]`. Vapi webhooks are short request/response
  (Vapi holds the audio, not Django), so they fit WSGI — but the design shall NOT
  attempt to hold long-lived duplex audio inside gunicorn. If concurrency pressure
  appears, the sanctioned path is more workers or a move to ASGI (`config/asgi.py`
  exists but is unwired), decided explicitly `[AUDIT-CS gotcha 1]`.
- **FR-PHN-9 (constraint).** Turn ceilings (`MAX_TOTAL_TURNS=25`, `REPLY_BUDGET=5`)
  are tuned for short chat; a phone call spans more turns `[AUDIT-CS gotcha 3]`. These
  shall be made channel-aware or env-raised for voice/phone before enabling the
  channel — not left to silently truncate a call.

### 4.5 WhatsApp media ingestion

- **FR-WA-1 (new).** The system shall receive inbound WhatsApp messages (text and
  media) via a WhatsApp Business API webhook receiver (Cloud API or BSP — the choice
  is a §6 external-interface decision, not designed here) `[AUDIT-VR Gaps §1]`.
- **FR-WA-2 (new).** The webhook shall verify the provider's signature/secret and
  fail closed, reusing the same webhook-auth discipline as FR-PHN-3 `[AUDIT-CS gotcha
  6; AUDIT-VR §1]`.
- **FR-WA-3 (new).** Inbound WhatsApp media shall be downloaded (Graph API media URL),
  run through the shared `sanitize_image()` → `_run_vision()` pipeline (FR-PHOTO-3),
  and stored keyed by the sender's `phone_hash` `[AUDIT-VR Gaps §1]`. This requires a
  new async ingestion module because the existing photo path is coupled to the
  synchronous multipart chat turn `[AUDIT-CS gotcha 5]`.
- **FR-WA-4 (new).** WhatsApp text shall be spotlight-wrapped as untrusted DATA
  (`wrap_untrusted`) before reaching any LLM prompt, identical to web chat
  `[AUDIT-CS §1; §2.3 S-7]`.
- **FR-WA-5 (new).** A WhatsApp conversation shall map to a `chat.Conversation`
  (async, multi-turn) and honor the same tier/guardrail/escalation rules; language
  may need to switch mid-thread more gracefully than the widget's "restart the
  session" behavior `[AUDIT-CS gotcha 10]`.

### 4.6 Mid-call image visibility (WhatsApp photo ↔ live phone call)

- **FR-MID-1 (new, the headline feature).** A photo a caller sends via WhatsApp
  *during or shortly before* a live Vapi call shall become available to the live
  assistant in near-real-time, so it can say "I received your photos, I'm looking at
  your IVT Greenline now" `[owner intent; AUDIT-VR Gaps §2]`.
- **FR-MID-2 (new).** The design shall follow the "vision happens out-of-band, voice
  consumes the text result" pattern: the image itself never enters the audio channel;
  instead (a) the WhatsApp photo is ingested and analyzed by `_run_vision()` keyed by
  `phone_hash` (FR-WA-3), and (b) a Vapi tool (registered in the tool-dispatch
  registry) is called with the caller's number, looks up the most recent photo-
  derived analysis, and returns a **text** summary the assistant speaks `[AUDIT-VR
  Gaps §2]`. This is explicitly the largest net-new piece and has no precedent to copy
  wholesale.
- **FR-MID-3 (new).** "Near-real-time" shall be bounded (NFR-LAT-4): the tool lookup
  reflects any photo ingested up to the moment of the tool call; if none is found, the
  assistant asks the caller to send one and can re-poll on a later turn.
- **FR-MID-4 (new).** The join key across WhatsApp media, the live call, and any web
  session shall be `phone_hash` (peppered SHA-256, already in `crm/models.py`,
  identical scheme in both repos) `[AUDIT-VR §4, Gaps §4]`.

### 4.7 Cross-channel identity (phone-hash join)

- **FR-ID-1 (new).** The system shall join a customer's activity across web chat,
  phone call, and WhatsApp using `phone_hash` as the shared key — no such join exists
  today (Conversation.public_id, VoiceCall.call_id, and WhatsApp media are otherwise
  independent identities) `[AUDIT-VR Gaps §4]`.
- **FR-ID-2 (new).** `phone_hash` shall remain non-reversible and used only for
  lookup/join, never as a directory index or in a URL (NFR-GDPR-3); the pepper stays
  distinct from `SECRET_KEY` (`PHONE_HASH_PEPPER`, `config/settings.py:127`)
  `[AUDIT-CS §3]`.
- **FR-ID-3 (new).** Returning-customer detection (existing `phone_hash` lookup at
  escalation `[AUDIT-CS §1, §3]`) shall be extended so a phone caller or WhatsApp
  sender is recognized as the same `Customer` when the number matches, surfacing prior
  equipment/session history to the specialist.

### 4.8 n8n automation

- **FR-N8N-1 (new).** The system shall support an n8n integration in **two independent
  directions**, mirroring the reuse source: (a) a **sink** that fires automatically on
  every completed call/lead, and (b) a **bot-callable tool** (`notify_n8n`) the
  assistant can invoke mid-conversation `[AUDIT-VR §3]`. The distinction must be
  preserved, not collapsed into one.
- **FR-N8N-2 (new).** The n8n sink shall be added alongside the existing sink set
  (`DBSink, EmailSink, WebhookSink, WordPressOffertSink`) using the existing
  `Sink`/`dispatch()` pattern with per-`(record, sink)` idempotency
  (`LeadDelivery`) `[AUDIT-CS §3; AUDIT-VR §4]`. The existing generic `WebhookSink`
  (built, disabled, `LEAD_WEBHOOK_URL`) is the natural template `[AUDIT-CS §3, §9]`.
- **FR-N8N-3 (new).** All payloads leaving to n8n shall be PII-masked/leak-scrubbed
  before dispatch (`redact_pii`), and shall carry an idempotency key so an n8n retry
  cannot double-fire a real-world action `[AUDIT-VR §3; global bus-at-least-once
  rule]`.
- **FR-N8N-4 (new).** `N8N_WEBHOOK_URL` shall be a dashboard-managed credential
  (FR-DASH-2), not a redeploy-only env var `[AUDIT-VR §5]`.

### 4.9 Escalation / callback / lead flow

- **FR-ESC-1 (baseline).** The three escalation triggers (RoutingRule override,
  specialist gate, unsupported-equipment) shall continue to converge on
  `STATE_ESCALATE` and produce a `ServiceRequest` lead `[AUDIT-CS §4]`.
- **FR-ESC-2 (baseline).** The escalation sub-flow (one-shot diagnostic enrichment →
  lazy `CONTACT_SLOTS` collection → regex yes/no approval → `create_and_dispatch`)
  shall be preserved for web/WhatsApp `[AUDIT-CS §1, §4]`.
- **FR-ESC-3 (new).** For the phone channel, escalation shall additionally support a
  **callback offer** (capture number + preferred time into the lead) and, where
  configured, warm transfer (FR-PHN-5). Callback is a lead attribute, not a scheduler.
- **FR-ESC-4 (new).** Lead delivery shall gain an n8n sink (FR-N8N-2) and, when the
  client provides URLs/field names, activate the currently-disabled `WebhookSink` /
  `WordPressOffertSink` `[AUDIT-CS §3, §9]`.

### 4.10 Admin dashboard configuration

- **FR-DASH-1 (new).** A **credentials editor** shall be added to the dashboard: a
  declarative catalog (`{group, name, label, secret, help}`) rendered as a grouped
  settings page, writing a `Credential` DB row and live-applying to
  `os.environ`/`settings` with no redeploy; `apply_all()` re-asserts DB overrides at
  boot — porting the happytime `dashboard/credentials.py` pattern `[AUDIT-VR §5]`.
  swedish-bot's dashboard has no credentials UI today `[AUDIT-VR §5]`.
- **FR-DASH-2 (new).** The credentials catalog shall manage the secrets **this app**
  needs to reach external services: `VAPI_PRIVATE_KEY`, `VAPI_WEBHOOK_SECRET`, Vapi
  phone-number/squad ids, `N8N_WEBHOOK_URL`, WhatsApp API token/secret, ElevenLabs
  API key + voice settings, `WIDGET_ALLOWED_ORIGINS` additions. Note: where a provider
  (e.g. ElevenLabs via Vapi's phone pipeline) stores its own key in Vapi's dashboard,
  that key is NOT duplicated here `[AUDIT-VR §5]`.
- **FR-DASH-3 (new).** A **Publish to Vapi** control shall let staff push assistant
  config live from a DB edit, sharing the payload builders with the CLI provisioner
  (one builder, two callers), with zero-drift making a no-edit save a cheap no-op
  `[AUDIT-VR §2, §5]`. Auto-publish-on-save (`HHT_AUTO_PUBLISH` analog) shall be an
  explicit on/off setting, defaulting OFF until a staging Vapi squad exists
  `[AUDIT-VR Risks]`.
- **FR-DASH-4 (new).** Vapi/voice/channel configuration (voice provider, voice id,
  voice settings JSON, per-role model provider, phone numbers, serverMessages) shall
  be editable from the dashboard. The existing Agent Config surface
  (`AgentPrompt.model_id/body/temperature/...`) is extended with voice/provider fields
  ("the field IS the extension seam") `[AUDIT-VR §2 P6]`. The existing decorative Flow
  builder (`FlowConfig`, zero runtime effect today) is NOT to be treated as an
  execution engine unless the FlowConfig→runtime gap is explicitly closed
  `[AUDIT-CS §6, gotcha 8]`.
- **FR-DASH-5 (new).** A **call monitor/log** view shall list calls with per-call
  transcript, tool-call log, outcome, and an on-demand "fetch full conversation from
  Vapi" reconciliation action `[AUDIT-VR §4, §5]`.
- **FR-DASH-6 (new).** A **channels/integration status** view shall show which
  channels are configured/healthy (Vapi reachability probe, n8n URL set, WhatsApp
  token set, ElevenLabs key set) — swedish-bot has no channel concept today
  `[AUDIT-CS §6]`.
- **FR-DASH-7 (baseline).** All new dashboard pages shall follow the existing
  `@staff_member_required` + HTMX-partial + `HX-Trigger` toast pattern `[AUDIT-CS §6]`.
- **FR-DASH-8 (new, safety).** The dashboard must not allow deletion of safety-critical
  transitions or weakening of baseline guardrails from any flow/graph editor
  ("guardrails cannot be deleted from the UI") — asserted from code on every publish
  `[AUDIT-VR §7]`.

### 4.11 Analytics

- **FR-AN-1 (baseline).** The existing analytics (`crm/analytics.py`: KPIs,
  breakdowns, trend, success_metrics vs targets) shall be preserved `[AUDIT-CS §3]`.
- **FR-AN-2 (new).** Analytics shall be extended to segment by **channel** (web
  chat / web voice / phone / WhatsApp), reporting resolution/deflection/escalation
  and returning-customer rates per channel, so the "triage nurse" deflection target
  is measurable per surface.
- **FR-AN-3 (new).** Phone-specific metrics (call duration, transfer disposition,
  callback offered/accepted, mid-call photo received) shall be surfaced from the new
  call records (FR-PHN-7) `[AUDIT-VR §4]`.
- **FR-AN-4 (new).** A per-tier breakdown (Tier 0 resolved / Tier 1 troubleshoot-then-
  escalate / Tier 2 info-gather / Tier 3 refuse) shall be reportable so scope-boundary
  drift is visible over time.

### 4.12 Cross-cutting / configuration

- **FR-CFG-1 (new).** A fail-closed boot guard (`DEBUG=0` only) shall refuse to boot
  if `VAPI_PRIVATE_KEY` / `VAPI_WEBHOOK_SECRET` are unset when the phone channel is
  enabled, mirroring the existing `PHONE_HASH_PEPPER != SECRET_KEY` guard
  `[AUDIT-VR §6; AUDIT-CS §9]`. Local dev/test needs a documented bypass so the guard
  doesn't stall development `[AUDIT-VR Risks]`.
- **FR-CFG-2 (new).** Any new agent role (e.g. a `voice`/`whatsapp_intake` role) added
  to `AGENT_ROLE_CHOICES` must add a unique classifier phrase to `conftest.py::_classify`
  or the test mock silently falls through to a generic default, masking bugs
  `[AUDIT-CS gotcha 9]`.

### 4.13 Conversation test suite

- **FR-TEST-1 (new).** A robust conversation test suite shall be specified in a
  **separate document** and shall extend the existing pytest + content-aware mocked-
  Gemini foundation and the 5-case "golden set" in `docs/TEST_STRATEGY.md`, rather
  than building a parallel harness `[AUDIT-CS §8]`. It must assert the tier boundaries
  of §2 (each tier's code-observable trigger), the per-brand policy, and the hard
  safety rules across all channels. This SRS only references it; the suite is designed
  elsewhere.

---

## 5. Non-functional requirements

### 5.1 Latency

- **NFR-LAT-1 (web chat, baseline).** Preserve current perceived latency; the SSE
  typing-dots UX masks full-turn compute `[AUDIT-CS §5]`.
- **NFR-LAT-2 (web voice).** End-to-end spoken-reply latency (user stops speaking →
  bot starts speaking) shall target ≤ ~2.5 s for Tier-0/1 turns. Because there is no
  LLM token streaming today, this budget assumes "full text then TTS"; if unmet, the
  sanctioned mitigation is genuine `generate_stream()` wiring (FR-VOICE-4b), decided
  explicitly `[AUDIT-CS gotcha 2]`.
- **NFR-LAT-3 (phone turn-taking).** Vapi handles STT/endpointing/barge-in; the Django
  webhook's tool/turn response shall return within Vapi's tool-timeout window
  (low single-digit seconds) so turn-taking stays natural for the elderly-caller
  persona. Slow KB/LLM work inside a tool call that risks the timeout shall be
  bounded or answered with a holding phrase `[AUDIT-VR §1, §4]`.
- **NFR-LAT-4 (mid-call photo).** From WhatsApp photo received → available to the
  live-call lookup tool shall target ≤ ~10 s (ingest + `_run_vision`), so "I received
  your photos" is truthful within a normal conversational pause `[FR-MID-3]`.

### 5.2 Availability & scale

- **NFR-AVAIL-1.** The phone/WhatsApp webhooks shall run behind the existing single
  Caddy block; no new ingress `[AUDIT-CS §9]`.
- **NFR-AVAIL-2 (WSGI constraint, acknowledged).** The deployment is synchronous
  WSGI/gunicorn (3 workers, `config.wsgi`), not ASGI, despite `config/asgi.py`
  existing `[AUDIT-CS §9, gotcha 1]`. Webhook-style phone integration fits this
  (Vapi holds the audio). Long-lived duplex audio must NOT be held in gunicorn
  workers. Concurrency headroom is addressed by worker count or an explicit ASGI move
  — this SRS acknowledges the constraint and forbids designs that silently violate it.
- **NFR-AVAIL-3.** Turn ceilings must be channel-aware before enabling voice/phone/
  WhatsApp (FR-PHN-9) so long conversations don't truncate `[AUDIT-CS gotcha 3]`.

### 5.3 GDPR / PII / data residency

- **NFR-GDPR-1.** Build on the existing `purge_pii` command (dry-run default; deletes
  Conversation+Message+Session and Customer+CustomerFile older than cutoff) — extend
  it to cover new call/WhatsApp records and downloaded media `[AUDIT-CS §3]`.
- **NFR-GDPR-2 (residency).** Every new AI/voice vendor (ElevenLabs, Vapi's telephony/
  LLM infra, WhatsApp, STT) shall be evaluated against the EU-residency posture the
  client evidently cares about (`config/settings.py:162` fail-closes Gemini to
  `europe-*`). Non-EU processing requires an explicit documented client acceptance,
  not an assumption `[AUDIT-CS §3, §9, gotcha 7]`.
- **NFR-GDPR-3.** `phone_hash` stays non-reversible, lookup-only, never in a URL or
  query string; pepper distinct from `SECRET_KEY` `[AUDIT-CS §3]`. No personal data in
  URL params anywhere in the new surfaces.
- **NFR-GDPR-4.** Call recordings/transcripts and WhatsApp media are personal data:
  retention must be covered by `purge_pii`, and storage stays on the EU-hosted VPS
  local disk unless a residency-cleared backend is chosen `[AUDIT-CS gotcha 12]`.

### 5.4 Security

- **NFR-SEC-1 (webhook auth).** All provider webhooks (Vapi, WhatsApp, n8n callbacks)
  shall verify signature/shared-secret and fail closed BEFORE body parsing — the chat
  API's anonymous model is the wrong trust model for webhooks `[AUDIT-CS gotcha 6;
  AUDIT-VR §1]`. Constant-time comparison; unconfigured secret rejects.
- **NFR-SEC-2 (idempotency).** Webhook processing shall be idempotent (reuse the
  `ServiceRequest.idempotency_key` / `LeadDelivery`-unique pattern and Vapi
  `call_id`-keyed `update_or_create`) so retries never double-fire real-world actions
  `[AUDIT-CS gotcha 14; AUDIT-VR §4]`.
- **NFR-SEC-3 (upload sanitization).** All inbound media (web, voice, WhatsApp) passes
  `sanitize_image()` (magic-byte/Pillow verify, type allowlist, size cap,
  decompression-bomb guard, EXIF/GPS strip) before storage or LLM `[AUDIT-CS §1]`.
- **NFR-SEC-4 (CORS).** The homepage-clone origin is added to the hand-rolled
  `WIDGET_ALLOWED_ORIGINS` allowlist; webhooks bypass this middleware (different path
  prefix) and rely on NFR-SEC-1 `[AUDIT-CS gotcha 11]`.
- **NFR-SEC-5 (injection).** Spotlighting (`wrap_untrusted`) and the `_LEAK`/output-
  guard apply to voice-transcribed and WhatsApp text identically to web `[AUDIT-CS §1;
  §2.3 S-7]`.
- **NFR-SEC-6 (secrets).** Vapi/ElevenLabs/WhatsApp/n8n secrets are stored via the
  credentials editor (`Credential` rows) or env, never in source or client-side code
  `[AUDIT-VR §5]`.
- **NFR-SEC-7 (CSRF).** Webhook endpoints are `@csrf_exempt` (they are not cookie-
  authed) but signature-authed instead `[AUDIT-VR §1]`.

### 5.5 Internationalization

- **NFR-I18N-1.** Swedish + English only, preserving the three existing mechanisms
  (in-code `T` dict, `{locale}` prompt directive, gettext `.po`) `[AUDIT-CS §1]`.
- **NFR-I18N-2.** Phone/voice language cannot come from a UI dropdown — it shall be set
  per phone number and/or detected from speech; WhatsApp language may need mid-thread
  switching more graceful than "restart the session" `[AUDIT-CS gotcha 10]`.

### 5.6 Cost

- **NFR-COST-1.** Reuse the existing model routing (cheap `flash-lite` for
  intake/router/safety, `flash` for specialist; ids/prices in `core/constants.py`)
  `[AUDIT-CS §1]`. Voice/phone add STT+TTS+telephony cost per minute — a per-channel
  cost ceiling shall be set and monitored (analytics FR-AN-2/3). Thinking budget stays
  0 by default (it eats output tokens) `[AUDIT-CS §1]`.
- **NFR-COST-2.** Context caching (`create_cache`, `CACHE_MIN_TOKENS=4096`) continues
  to amortize large-PDF specialist calls `[AUDIT-CS §1; core/constants.py:58]`.

### 5.7 Deployment constraints (acknowledged)

- **NFR-DEP-1.** New URLs sit behind the existing Caddy → gunicorn → Postgres stack;
  cron for `resend_leads`/`purge_pii`/`summarize_idle` is currently unconfigured and
  remains an ops gap to close before relying on lead-retry/PII-purge automation
  `[AUDIT-CS §9]`.
- **NFR-DEP-2.** No S3/GCS; media on bind-mounted local disk `[AUDIT-CS gotcha 12]`.

---

## 6. External interfaces (requirements level, not design)

- **INT-VAPI.** Vapi (`api.vapi.ai`) — inbound phone via a provisioned assistant/squad;
  outbound REST for provisioning (Bearer `VAPI_PRIVATE_KEY`); webhook server-messages
  (`tool-calls`, `status-update`, `end-of-call-report`) HMAC/secret-verified. Vapi is
  the audio/STT/turn-taking layer for phone; Django is control+data plane
  `[AUDIT-VR §1, §2]`. Provider keys for the voice model may live in Vapi's own
  dashboard (no public Vapi credential API) `[AUDIT-VR §5]`.
- **INT-ELEVENLABS.** ElevenLabs TTS — for the **web widget voice mode** (direct
  browser/Web-SDK integration; no precedent in the reuse source, which only used
  ElevenLabs via Vapi's phone pipeline) and, on phone, as Vapi's configured voice
  provider `[AUDIT-VR Gaps §3, §2 P6]`. Requirements: API key via credentials editor;
  voice id + settings dashboard-editable; EU-residency decision (NFR-GDPR-2).
- **INT-WHATSAPP.** WhatsApp Business API — inbound messages + media. Two provisioning
  options exist at the requirements level (Meta **Cloud API** direct, or a **BSP/
  provider**); the choice is deferred to design, not made here `[AUDIT-VR Gaps §1]`.
  Requirements: signed webhook (NFR-SEC-1), Graph-API media download (FR-WA-3),
  phone-hash keying (FR-MID-4).
- **INT-N8N.** n8n — bidirectional: outbound sink on every call/lead + bot-callable
  `notify_n8n` tool; fire-and-forget POST to `N8N_WEBHOOK_URL`, PII-masked, idempotent
  `[AUDIT-VR §3]`.
- **INT-GEMINI.** Gemini via Vertex AI (`europe-north1`, EU residency fail-closed) —
  unchanged; the shared brain for all channels (specialist/router/intake/safety/
  vision/summarizer) `[AUDIT-CS §1, §9]`. 2.5 family only confirmed callable
  (`core/constants.py`); re-spike for 3.x on the client's own project.

---

## 7. Acceptance criteria per FR (testable)

Web chat baseline (FR-CHAT-1..4): existing test suite (`test_api.py`,
`test_orchestrator.py`, `test_golden.py`) passes unchanged after every new-channel
change; the FSM, guardrail, gate, and lead tests are green `[AUDIT-CS §8]`.

- **AC-HOME-1/2.** Loading the cloned homepage at its new origin, the widget opens and
  completes a full session against the Nordland backend with the clone origin in
  `WIDGET_ALLOWED_ORIGINS`; a preflight `OPTIONS` from the clone origin returns the
  CORS allow headers; an origin NOT in the list is rejected.
- **AC-HOME-3.** The clone renders responsively on mobile/desktop; keyboard trap,
  Escape-to-close, reduced-motion, and language switch behave as on the demo page.
- **AC-VOICE-1.** In voice mode, a spoken "my IVT Vent 402 filter is dirty" reaches
  `process_turn` as text and produces the identical FSM transition and lead outcome as
  the typed equivalent (assert same `Session` fields).
- **AC-VOICE-3.** Changing the ElevenLabs voice id in the dashboard changes the
  synthesized voice with no redeploy; the key is never present in client-delivered JS.
- **AC-VOICE-4/NFR-LAT-2.** Measured spoken-reply latency for a Tier-0 turn is reported;
  if > budget, the doc's fallback (FR-VOICE-4b) is the recorded remediation, not an
  ad-hoc change.
- **AC-VOICE-5.** Denying mic permission falls back to text UI with a visible notice;
  no conversation state is lost.
- **AC-VOICE-6 / AC-safety.** A spoken refrigerant-work request is refused (no DIY
  step spoken) and escalates — asserted against `guardrails.is_unsafe()` firing before
  TTS.
- **AC-PHOTO-2/3.** A photo uploaded in voice mode and a photo arriving via WhatsApp
  both produce identical `_run_vision` `CaseState.slots` (manufacturer/model/serial/
  error_code) to a web-chat upload of the same image; the OCR code path is the shared
  function, verified by test (no duplicated OCR logic).
- **AC-PHOTO-4/5.** The 9th image in one conversation is rejected across channels; on
  escalation, uploaded photos appear as `CustomerFile` rows deduped by sha256.
- **AC-PHN-3/NFR-SEC-1.** A Vapi webhook with a missing/invalid signature is rejected
  with 401 before body parsing; a valid one dispatches. Unconfigured secret → reject.
- **AC-PHN-4.** A phone turn routes through the same orchestrator: the same
  "unsupported brand" utterance escalates with `escalation_reason = "unsupported"`
  as on web `[AUDIT-CS §1, §4]`.
- **AC-PHN-6.** Running the provisioner twice with no config change performs **zero**
  Vapi writes (hash-oracle no-op), asserted by the dry-run recorder `[AUDIT-VR §2]`.
- **AC-PHN-7/NFR-SEC-2.** A duplicate `end-of-call-report` for the same `call_id`
  creates exactly one call record; the record is written before summary/sink work.
- **AC-PHN-9.** With voice enabled, a call exceeding the old 25-turn chat ceiling does
  not truncate (channel-aware ceiling verified).
- **AC-WA-2/3.** A WhatsApp media webhook with a bad signature is rejected; a valid one
  downloads, sanitizes, and stores the image keyed by `phone_hash`, then `_run_vision`
  extraction is available for lookup.
- **AC-MID-1/2/NFR-LAT-4.** A photo sent via WhatsApp during a call is returned as a
  **text** summary by the Vapi lookup tool within the latency budget; the image never
  enters the audio channel; the assistant can truthfully say "I received your photos."
- **AC-ID-1/3.** A caller whose number matches a prior web `Customer` is recognized as
  the same customer (via `phone_hash`), and prior equipment history is available to the
  specialist/lead.
- **AC-N8N-1/2/3.** The n8n sink fires on a completed lead with a PII-masked, idempotent
  payload; a retried delivery does not create a second real-world action; the bot-
  callable `notify_n8n` tool and the automatic sink are distinct and both testable.
- **AC-ESC-3.** A phone escalation captures a callback number+time into the lead;
  warm transfer (if configured) connects the live call, else async-lead+callback is the
  floor.
- **AC-DASH-1/2.** Setting a credential in the dashboard live-applies to
  `settings`/`os.environ` with no redeploy and persists across boot (`apply_all`).
- **AC-DASH-3.** Editing an assistant and clicking Publish updates Vapi; a no-edit
  re-save is a zero-write no-op; auto-publish defaults OFF.
- **AC-DASH-5.** The call log shows transcript + tool calls for a completed call and can
  fetch the full conversation from Vapi on demand.
- **AC-DASH-8.** No dashboard flow/graph edit can remove a safety-critical transition or
  weaken a baseline guardrail (asserted from code on publish).
- **AC-AN-2/3/4.** Analytics segment resolution/deflection/escalation by channel, show
  phone-specific metrics, and report the Tier 0–3 breakdown.
- **AC-CFG-1.** With `DEBUG=0` and phone enabled, boot fails if `VAPI_PRIVATE_KEY`/
  `VAPI_WEBHOOK_SECRET` unset; documented dev/test bypass works.
- **AC-GDPR-1/4.** `purge_pii --days N` removes new call/WhatsApp records and downloaded
  media past the cutoff (dry-run shows counts first).

---

## 8. Traceability appendix (FR → code that satisfies it, or "new")

| FR | Existing code that satisfies / hosts it | Verdict |
|---|---|---|
| FR-CHAT-1..4 | `chat/views.py`, `chat/urls.py`, `chat/orchestrator.py`, `crm/leads.py`, `crm/sinks.py` | Baseline, preserve |
| FR-HOME-1 | `templates/widget_demo.html` (template pattern), `static/widget/nordland-widget.js` (embed) | New page, reuse embed |
| FR-HOME-2 | `config/settings.py:32` `WIDGET_ALLOWED_ORIGINS`; `core/middleware.py::WidgetCorsMiddleware` | Config change only |
| FR-VOICE-1..6 | `chat/orchestrator.py::process_turn` (reused brain); `core/services/gemini.py::generate_stream` (unused, for 4b) | New transport + widget UI |
| FR-PHOTO-1,4,5 | `chat/uploads.py::sanitize_image`, `chat/orchestrator.py::_run_vision`, `chat/views.py:85`, `crm/leads.py::attach_customer_files` | Baseline, reuse |
| FR-PHOTO-2,3,6 | same pipeline, must be made callable async | Refactor to shared fn |
| FR-PHN-1..9 | none — Vapi layer is net-new; port `voice/signing.py`, `voice/provision.py`, `core/services/vapi.py`, `voice/webhooks.py` patterns from happytime `[AUDIT-VR §1,§2,§4]` | New (new `voice/` app) |
| FR-WA-1..5 | none — WhatsApp integration absent in both repos `[AUDIT-VR Gaps §1]`; reuse `sanitize_image`/`_run_vision`/`wrap_untrusted` | New |
| FR-MID-1..4 | none — mid-call image injection has no precedent `[AUDIT-VR Gaps §2]`; `phone_hash` (`crm/models.py`) is the join key | New (largest piece) |
| FR-ID-1..3 | `crm/models.py::phone_hash` (exists); returning-customer lookup in `chat/orchestrator.py` | Extend existing hash |
| FR-N8N-1..4 | `crm/sinks.py` (`Sink`/`dispatch`/`WebhookSink` template), `LeadDelivery` idempotency | Extend sinks + new tool |
| FR-ESC-1,2 | `chat/orchestrator.py::_escalate_step`, `crm/leads.py` | Baseline, preserve |
| FR-ESC-3,4 | callback/warm-transfer new; `WebhookSink`/`WordPressOffertSink` exist-but-disabled | Partly new |
| FR-DASH-1,2 | none — no credentials UI in swedish-bot dashboard `[AUDIT-VR §5]`; port happytime `dashboard/credentials.py` | New |
| FR-DASH-3,4 | `dashboard/views.py` agent config (`AgentPrompt`); `FlowConfig` (decorative) `[AUDIT-CS §6]`; port `dashboard/publish.py` | New publish + extend agent fields |
| FR-DASH-5,6 | none — no call/channel views `[AUDIT-CS §6]` | New |
| FR-DASH-7,8 | `dashboard/` HTMX+staff-auth pattern (exists); code-asserted guardrails `[AUDIT-VR §7]` | Reuse pattern |
| FR-AN-1 | `crm/analytics.py` | Baseline |
| FR-AN-2,3,4 | extend `crm/analytics.py` with channel/tier/phone dimensions | New |
| FR-CFG-1 | `config/settings.py` fail-closed guard pattern (`PHONE_HASH_PEPPER` check) | Extend |
| FR-CFG-2 | `conftest.py::_classify`, `kb/seed_prompts.py` | Extend (fragile coupling) |
| FR-TEST-1 | `tests/`, `conftest.py`, `docs/TEST_STRATEGY.md` golden set | Separate doc extends |

---

## Open items to confirm with the client before build

1. Load the loose `.txt` content (IVT Geo 412C / Bosch Greenline HEC-E / IVT Vent 402)
   as real `MachineDocument` rows and/or inspect `nordland.sql` for prod KB, so the
   Tier-0 deflection target is actually reachable in production `[AUDIT-CS §7, gotcha 13]`.
2. Data-residency acceptance for ElevenLabs / Vapi / WhatsApp / STT (EU or explicit
   non-EU sign-off) `[NFR-GDPR-2]`.
3. WhatsApp provisioning path: Meta Cloud API direct vs a BSP `[INT-WHATSAPP]`.
4. Whether phone warm-transfer to a human line is in scope for v1 or callback-only
   `[FR-PHN-5]`.
5. Real Nordland WordPress offert field names + webhook URL to activate the disabled
   sinks `[AUDIT-CS §3, §9]`.
6. Cron/ops owner for `resend_leads` / `purge_pii` / `summarize_idle` `[NFR-DEP-1]`.
