# Nordland VVS Bot Expansion — Master Plan Index (2026-07-12)

Planning-only engagement. Orchestrated by Fable; audits and drafts produced by parallel
Sonnet/Opus agents in three waves; this index and the review verdicts below are the
orchestrator's own synthesis. **No source code was modified.**

## Document set (read in this order)

| # | Document | Role | Author wave |
|---|----------|------|-------------|
| 1 | [2026-07-12-audit-current-state.md](2026-07-12-audit-current-state.md) | Ground truth of the existing system (FSM orchestrator, KB, CRM, widget, dashboard, deploy) | Wave 1 (Sonnet) |
| 2 | [2026-07-12-audit-budtender-voice-reuse.md](2026-07-12-audit-budtender-voice-reuse.md) | What ports from `happytime-budtender/voice` (itself a fork of this repo): signing, Vapi client, credentials catalog, zero-drift publish, n8n tool, callfetch | Wave 1 (Sonnet) |
| 3 | [2026-07-12-srs-nordland-bot.md](2026-07-12-srs-nordland-bot.md) | Requirements: 4 confidence tiers, per-brand policy, 8 safety rules, ~60 FRs + NFRs + acceptance criteria + traceability | Wave 2 (Opus) |
| 4 | [2026-07-12-design-telephony-vapi-whatsapp.md](2026-07-12-design-telephony-vapi-whatsapp.md) | Vapi phone channel, WhatsApp media, mid-call photo injection (controlUrl push), n8n role, dashboard config, security, WSGI verdict | Wave 2 (Opus) |
| 5 | [2026-07-12-design-homepage-widget-voice.md](2026-07-12-design-homepage-widget-voice.md) | nordlandvvs.se homepage clone + widget embed; ElevenLabs voice mode (Option B: Scribe STT + existing pipeline + TTS proxy) | Wave 2 (Sonnet) |
| 6 | [2026-07-12-test-plan-conversations.md](2026-07-12-test-plan-conversations.md) | 46 scripted conversation scenarios in 9 categories, grounded in real KB error codes; coverage matrix; CI strategy; metrics | Wave 2 (Opus) |
| 7 | [2026-07-12-sprint-plan.md](2026-07-12-sprint-plan.md) | 7 one-week sprints, task IDs with FR citations, dependency graph, risk register, owner-decision table, deferred list | Wave 3 (Sonnet) |

## Bot scope in one paragraph (the owner's intent, made binding)

Triage nurse, not surgeon. The bot autonomously resolves only Tier-0 low-stakes problems
(dirty filter, restart, thermostat, breaker) where confidence ≥ 0.70 and the fix is in the
loaded docs; runs a bounded troubleshoot (5-reply budget) then escalates; for undocumented
machines and non-serviced brands it only gathers structured context (machine identity,
symptoms, photos, contact) and creates a lead/callback; and for the 8 safety classes
(electrical, refrigerant, gas, leaks, …) it escalates immediately with zero DIY instructions.
Escalation is always the async lead/callback flow — there is no live human transfer except
the optional phone warm-transfer, which is explicitly a net-new owner decision.

## Orchestrator review verdicts (cross-doc conflicts, resolved)

The sprint agent found 4 items (sprint plan §8); I verified the two load-bearing ones
against the actual doc text. Rulings:

1. **Voice latency (SRS NFR-LAT-2 ≤2.5s vs widget doc ~2–5s typical) — RESOLVED BY RULING:**
   the 2–5s budget is dominated by the existing non-streaming FSM turn (1–4s), which chat
   users already experience. v1 acceptance range is **2–5s**; NFR-LAT-2's ≤2.5s becomes the
   *streaming-era target*, reachable only via the SRS's own sanctioned fallback (FR-VOICE-4b:
   real `gemini.generate_stream()` wiring). Do not chase 2.5s in v1 with hacks. Sprint task
   S3-T9 measures; the streaming refactor stays in the deferred list until measured need.
2. **Test plan §3.2 conflates web-voice and phone mechanics — CONFIRMED DEFECT, scoped fix:**
   phone calls do not run the FSM (`CaseState.turns`, chips, `_is_yes` regex are web-only per
   design-telephony §6). Before implementing phone-channel tests (Sprint 4+), split §3.2 into
   "web voice deltas" (as written) and "phone deltas" (tool-call/webhook assertions per
   design-telephony §4–5). Tracked as S4-T12.
3. **SRS FR-PHN-9 turn-ceiling "channel-aware for voice/phone" — half-applicable as worded:**
   valid for web voice; meaningless for phone (no FSM turns). Re-read it as: web-voice turn
   ceiling env-tunable; phone call duration governed by Vapi assistant config
   (maxDurationSeconds + idle messages). Tracked as S4-T9.
4. **Photo-upload decoupling — NON-CONFLICT, verified independently:** widget keeps the
   coupled multipart endpoint for v1 (widget doc §5.2); the WhatsApp path never uses it —
   it calls the shared `sanitize_image()` → vision factoring server-side, which is exactly
   what SRS FR-PHOTO-3 requires. All three docs agree.

## Riskiest assumptions (de-risk first — Sprint 2 spikes)

1. **Vapi `controlUrl` add-message injection on a real inbound call** — the headline
   "I received your photos, I'm looking at your IVT Greenline" moment depends on it.
   Fallback if the spike fails: `check_photos` polling tool (designed, documented).
2. **ElevenLabs Scribe Swedish STT quality in-browser** — voice mode depends on it.
   Fallback: ElevenLabs Agents platform (Option A, documented).

## Decisions the owner must make (consolidated; full table in sprint plan §6)

- WhatsApp path: Cloud API direct vs BSP; which number.
- Call-recording retention + GDPR sign-off (recommendation in docs: don't retain audio).
- Warm-transfer on phone: in scope or lead-only like every other channel?
- Load the Greenline/Vent/Geo `.txt` manual content into the KB as seeded rows (the
  filtration brands are referral-only until manuals are loaded).
- ElevenLabs/Vapi EU data-residency acceptance.

## What was deliberately NOT done

No code, no migrations, no config changes, no test implementations — per the engagement
brief. Sprint 1 (test harness on the *existing* chat pipeline + homepage clone) is the
first implementation step and is fully specified.
