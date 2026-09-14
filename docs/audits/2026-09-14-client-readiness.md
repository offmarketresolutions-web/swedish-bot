# Client-readiness audit — 2026-09-14

A 45-agent sweep over every customer-facing surface (i18n strings, seeded prompts,
orchestrator hard-coded text, CRM writes, and the spec-conformance rules), with every
finding independently attacked by a skeptic agent before it was kept.

**41 findings, all verified. 10 critical.** What follows is the state of each.

## Fixed and tested

| # | What was wrong | Where |
|---|---|---|
| 1 | Gas/refrigerant emergency replies said *"En tekniker från Nordland larmas nu"*. Nothing was dispatched: a lead exists only after the customer supplies name, phone, email, postcode, address **and** approves. Someone told to evacuate very often never finishes that, and believed help was coming. | `chat/i18n.py` |
| 2 | `_is_yes("yes_save")` was `False` — the chip posts its *value*, and `_` is a word character, so `\byes\b` never matched inside it. Tapping "Ja" on the post-fix details offer was read as a refusal and the whole post-solve capture silently never ran. Typing "ja" worked. | `chat/orchestrator.py` |
| 3 | `"köldmedieläckage"` — the standard Swedish word, and the word the bot's *own reply* uses — did not trigger the refrigerant emergency. Swedish welds noun and verb into one token; the pattern wanted them separate. Same for `gasledningen`, `gasolflaskan`, `gasröret`. | `chat/orchestrator.py` |
| 4 | `"ja men skicka inte"` and `"ja, men inte än"` dispatched a lead and wrote `consent_to_contact=True`. Judging only the first clause fixed one failure (consent + correction) and created another (consent + withdrawal). | `chat/orchestrator.py` |
| 5 | Seeded prompts *taught* the over-promise: the specialist tone rule modelled `"I'll line up a Nordland tech"` and the safety prompts ordered the model to "say a technician is being alerted now". | `kb/seed_prompts.py` |
| 6 | A photo of the **display** had its alarm code read correctly by vision and then discarded — the whole OCR block was gated on a readable *model*, which a display does not carry. The bot asks for exactly that photo. | `chat/orchestrator.py` |
| 7 | `S13-FORM-NOT-A-BOOKING` matched only past-tense confirmations **and** returned early whenever a lead existed — inert on 39 of 44 real conversations. A lead is not a booking. | `tools/eval/spec_conformance.py` |
| 8 | `test_freshly_seeded_prompts_need_no_addendum` only checked the five specialist roles, so `INTELLIGENT_INTAKE` could miss a rule while the test passed. | `tests/test_prompt_contract.py` |

Prompt bodies are the source of truth for these rules; `chat/prompts.py::_CONTRACT_ADDENDA`
back-fills only prompt rows seeded before a rule existed (`seed_kb` is no-clobber).

## Open — triaged, not fixed

Ranked by what a customer or the owner actually loses. None of these are safety-critical.

**High**
- `chat/guardrails.py` — Swedish water/pressure nouns lack `\w*`, so the definite form (how
  Swedes actually write) escapes the noun veto. Same bug class as #3 above.
- `chat/i18n.py` — every dead-end close still ends *"Nordland VVS hör av sig"* even when no
  lead exists; the out-of-area decline states the bot books visits.
- `chat/casestate.py` — a brand correction at the approval step leaves the old model and the
  old `Machine` FK on the lead, so the office receives a mismatched pair.
- `chat/orchestrator.py` — `Session.status` sticks on `escalated` for refused and
  unreachable escalations; never set to resolved/closed.
- `tools/eval/spec_conformance.py` — three more rules too narrow to fire on a realistic
  violation (`S4-BRAND-PRESERVED`, `S11-SUMMARY-STATES-GAPS`, `S7-SUDDEN-NOT-A-SETTING`),
  and any generic safety footer in a turn disables every forbidden-guidance hit in it.

**Medium / low** — 25 further findings: spec requirements with no conformance rule at all
(§12 previous-installation override, §13 invented URLs, §5 anti-invention list), the
English-only casing nouns in the guardrail disassembly branch, dotted alarm codes truncated
before reaching the lead, `Customer.city`/`property_type` never written.

Full verified output with per-finding evidence and the refutation reasoning:
`.claude/projects/<session>/subagents/workflows/wf_68cb738a-b27/journal.jsonl`.

## Standing risk

Two independent sweeps on the same day each found bugs the other missed, and hands-on
clicking found one that 934 passing tests did not. Treat "no known criticals" as the current
state of knowledge, not as a guarantee.
