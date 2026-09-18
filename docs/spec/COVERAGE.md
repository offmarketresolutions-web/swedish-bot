# Spec coverage matrix — `docs/spec/owner-workflow-spec.md`

What "100% conformance to the Bobby letter" means, requirement by requirement.

**Method.** Every numbered section and every sub-bullet that states a behaviour was turned
into a checkable requirement with a stable ID (`R-<section>.<n>`). Status was assigned by
**opening and reading the code**, never by inferring from a filename or a function name.
Pure example enumerations in the spec (symptom lists, comfort-setting examples) are collapsed
into one requirement each; lists where each item has *separate* code coverage (the §7/§8/§10
forbidden-action lists, the §1 field list, the §13 transfer fields) are kept granular, because
that is exactly where coverage differs item by item.

**Status vocabulary**

| Status | Means |
|---|---|
| IMPLEMENTED | Code exists and was read. The *test* column may still be empty — that is stated, not hidden. |
| PARTIAL | Behaviour is only in prompt text with no test asserting it; or the code covers some phrasings/paths but demonstrably not others. |
| MISSING | No code, no prompt rule, no test. |
| NOT-CHECKABLE | A human process, not software. |

**Judging rules applied**

- *Prompt-text-only is PARTIAL.* `seed_kb` is no-clobber (`kb/management/commands/seed_kb.py:152-161`
  uses `get_or_create`), so a rule that lives only in a seeded `AgentPrompt.body` can be
  silently absent in any install whose prompt row predates the rule.
  `chat/prompts.py::_CONTRACT_ADDENDA` back-fills exactly five contract keys — everything
  else in a prompt body is unprotected.
- *Regexes are judged adversarially against Swedish definite/welded forms.* A pattern that
  only matches the indefinite separate-word form ("byta filtermassa" but not "byt filtermassan")
  is PARTIAL.
- Conformance rules cited are from `tools/eval/spec_conformance.py` (**15 rules**, not 16 —
  see §"Counts" note).

---

## §0 — Scope and top-level policy (letter preamble)

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-0.01 | Service scope covers heat pumps (most manufacturers), water pumps, wells/domestic water, pressure tanks & pump control, water filters, water treatment | IMPLEMENTED | `chat/orchestrator.py:636` `SERVICED_FAMILIES`; `chat/orchestrator.py:668` `_GENERAL_ROLE_BY_FAMILY` | `tests/test_general_specialists.py::test_general_role_selection_per_family` | | Three families, not six: pressure tanks/wells/water-treatment are folded into `water_pump_well` / `water_filtration`. |
| R-0.02 | Use verified general Nordland knowledge FIRST for system-level problems | PARTIAL | `chat/context.py:82` `collect_general_knowledge` (runs every specialist turn, both modes) | `tests/test_rag_corpus.py` | | In manual mode general knowledge and the manual are injected *together*; the seeded specialist prompt then ranks the manual 3rd, not 1st. See R-6.02 and the §5/§6 ambiguity note. |
| R-0.03 | Move to the exact model manual only when the answer depends on model-specific information | PARTIAL | `kb/seed_prompts.py:189` HARD RULE (grounding); `chat/orchestrator.py:1230` `context.machine_pdf_context` | | | Prompt-text rule. Code always loads the manual when a machine is confirmed; nothing defers manual load on "is this model-specific?". |
| R-0.04 | If no safe verified customer-level action is available, offer Nordland VVS service | IMPLEMENTED | `chat/orchestrator.py:1300-1325` (`escalate` when `conf < CONFIDENCE_GATE` or `in_docs=false`) | `tests/test_orchestrator.py::test_low_confidence_escalates` | | |
| R-0.05 | If equipment previously worked and suddenly changed with no user-setting explanation, offer service | IMPLEMENTED | `chat/orchestrator.py:1216-1218` (sudden onset clamps budget to 3, then forced wrap-up → escalate) | `tests/test_scenarios/test_o_onset_comfort.py::test_sudden_onset_clamps_budget_to_three` | S7-SUDDEN-NOT-A-SETTING | |

## §1 — Shared case state / backend

The shared object is `chat/casestate.py::new_case_state()` (persisted on
`Conversation.case_state`) plus the typed flush into `crm.Session`
(`chat/casestate.py:104` `flush_to_session`).

| ID | Requirement (field preserved) | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-1.01 | main category | IMPLEMENTED | `casestate.py:13` `slots.category`; `Session.category` | `tests/test_casestate_s2.py::test_flush_writes_new_session_columns` | | |
| R-1.02 | equipment subtype | IMPLEMENTED | `casestate.py:18` `slots.subtype`; `chat/intake.py:168` | `tests/test_casestate_s2.py::test_bulk_extract_merges_only_into_empty` | | JSON only — no `Session` column, so it never reaches the dashboard or the lead payload. |
| R-1.03 | manufacturer | IMPLEMENTED | `slots.brand`; `Session.manufacturer` (`casestate.py:117`) | `tests/test_casestate_s2.py::test_flush_writes_new_session_columns` | S4-BRAND-PRESERVED | |
| R-1.04 | customer-entered model text (raw) | IMPLEMENTED | `casestate.py:18` contract + `orchestrator.py:457` `_repair_model_slot`; never overwritten by a catalog name | `tests/test_casestate_s2.py::test_model_slot_never_overwritten`; `tests/test_model_named_verbatim.py::test_a_good_answer_is_never_downgraded_to_the_catalog_name` | S3-MODEL-NOT-GUESSED | |
| R-1.05 | confirmed catalog model | IMPLEMENTED | `orchestrator.py:708` `_bind_confirmed` → `cs["model_confirmed"]`; `Session.machine` only when confirmed (`casestate.py:113`) | `tests/test_model_named_verbatim.py::test_a_repaired_model_binds_instead_of_disambiguating` | | |
| R-1.06 | catalog machine ID | IMPLEMENTED | `cs["machine_id"]` (`orchestrator.py:709`) | as above | | |
| R-1.07 | catalog-match confidence | IMPLEMENTED | `cs["match_confidence"]` (`orchestrator.py:710`, `:764`) | | | No test pins the value; surfaced only in `_debug_snapshot`. |
| R-1.08 | serial number | IMPLEMENTED | `slots.serial`; `Session.serial`; OCR path `orchestrator.py:1911` | `tests/test_scenarios/test_e_photo.py` | | |
| R-1.09 | alarm code | IMPLEMENTED | `slots.error_code`; `Session.error_code`; `sanitize.extract_error_code` | `tests/test_casestate_s2.py::test_pre_escalate_diag_does_not_re_ask_for_an_error_code_already_known` | S3-MODEL-IS-NOT-AN-ALARM | |
| R-1.10 | alarm text | IMPLEMENTED | `slots.alarm_text` (`intake.py:180`, `orchestrator.py:1019`) | | | JSON only, no `Session` column. Reaches the form prefill (`chat/views.py:187`) but not the lead payload. |
| R-1.11 | problem description | IMPLEMENTED | `slots.problem`; transient `session._problem_text` (`casestate.py:167`) | `tests/test_scenarios/test_n_gap_fixes.py::test_gap2_symptom_opener_lands_category_and_problem_no_apology` | | No `Session` column — deliberately transient. |
| R-1.12 | symptoms (separate from problem description) | **MISSING** | — | | | No `symptoms` slot exists. The specialist prompt has a `{symptoms}` placeholder and `orchestrator.py:1228` passes `symptoms=""` **unconditionally** — the field is always blank in every rendered specialist prompt. |
| R-1.13 | when the problem started | PARTIAL | `slots.onset`; `Session.onset` | `tests/test_scenarios/test_o_onset_comfort.py` | S7-ONSET-ESTABLISHED | Only the coarse enum (`sudden`/`gradual`/`always`) is captured; no date/"since when" value. |
| R-1.14 | whether it appeared suddenly or has always existed | IMPLEMENTED | `slots.onset` enum; `intake.py:139` `_ONSETS` | `tests/test_scenarios/test_o_onset_comfort.py::test_gradual_onset_keeps_full_budget` | S7-ONSET-ESTABLISHED | |
| R-1.15 | operating context | PARTIAL | `slots.operating_context` (`intake.py:193`, `orchestrator.py:1019`) | | | Captured and then dropped: not flushed to `Session`, not in the lead payload, not in the form prefill, and **not injected into any specialist prompt**. |
| R-1.16 | pressure and temperature readings | PARTIAL | `slots.readings` (`intake.py:247`, `orchestrator.py:1025`) | | | Same dead-end as R-1.15: captured, never rendered into a prompt, never flushed, never leaves the JSON blob. |
| R-1.17 | previous checks | IMPLEMENTED | `cs["report"]["checks"]` via `orchestrator.py:1074` `_record_checks_given` | `tests/test_casestate_s2.py::test_check_memory_accumulates_then_resolves` | | |
| R-1.18 | results of previous checks | IMPLEMENTED | `orchestrator.py:1032-1073` (`check_results` → per-check `step_hint` matching) | `tests/test_casestate_s2.py::test_two_checks_reported_with_different_outcomes_are_not_collapsed` | | |
| R-1.19 | uploaded photos | IMPLEMENTED | `chat/models.py` `Message.image`; `crm/leads.py:64` `attach_customer_files`; `slots.nameplate_photo` flag | `tests/test_file_hub.py` | | Case state keeps only a boolean; the images themselves live on `Message`/`CustomerFile`. |
| R-1.20 | OCR results | IMPLEMENTED | `slots.ocr_text` (`orchestrator.py:1919`); `_run_vision` | `tests/test_scenarios/test_e_photo.py` | | |
| R-1.21 | postcode | IMPLEMENTED | `slots.postal_code`; `Session.postal_code` | `tests/test_casestate_s2.py::test_postcode_normalized_and_skipped_at_contact` | S12-POSTCODE-NORMALISED | |
| R-1.22 | service-area status | IMPLEMENTED | `cs["service_area"]`; `Session.service_area_status` (`casestate.py:148`) | `tests/test_scenarios/test_p_service_area.py::test_inside_area_escalates_and_rides_lead` | | |
| R-1.23 | matched service-area polygon | IMPLEMENTED | `cs["report"]["service_area_name"]`; `Session.service_area_name` | `tests/test_scenarios/test_p_service_area.py::test_border_area_adds_coverage_line` | | Name only, not the polygon id. |
| R-1.24 | installer or seller | IMPLEMENTED | `slots.installer`; `Session.installer` | `tests/test_scenarios/test_p_service_area.py::test_outside_with_listed_installer_upgrades_to_inside` | | |
| R-1.25 | previous Nordland installation status | PARTIAL | `slots.installer` enum `nordland\|bylunds\|nordborr\|other` (`intake.py:138`) | `tests/test_geo.py::test_check_with_override_upgrades_outside_to_inside` | | Doubles as the installer field; there is no separate "was it a Nordland installation" boolean, and it is only ever asked on the outside-area path (`orchestrator.py:1404`). |
| R-1.26 | warranty information | **MISSING** | `casestate.py:18` declares `"warranty"` in `EXTRA_SLOTS` | | | **Dead slot.** Grepped the whole tree: nothing ever writes it — not `bulk_extract`, not `_apply_extracted_facts`, not vision, not the dashboard. It is initialised to `None` and stays `None` forever. |
| R-1.27 | recommended form type | IMPLEMENTED | `cs["report"]["form_type"]` (`orchestrator.py:245`); `Session.form_category` | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_post_lead_thanks_and_tracking` | | |
| R-1.28 | form-submission status | IMPLEMENTED | `cs["report"]["form_status"]`; `Session.form_shown` (distinct from `booking_requested`) | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_post_lead_thanks_and_tracking` | S13-FORM-NOT-A-BOOKING | |
| R-1.29 | booking status | IMPLEMENTED | `Session.booking_requested` set only on consent (`orchestrator.py:1696`) | `tests/test_casestate_s2.py::test_consent_is_recorded_on_the_answer_not_on_the_question` | S13-FORM-NOT-A-BOOKING | |
| R-1.30 | The case object follows the customer through the complete pipeline | IMPLEMENTED | `orchestrator.py:326` `process_turn` loads/saves `conversation.case_state` every turn; `_history_parts` carries transcript + images to every agent | `tests/test_orchestrator.py::test_history_and_files_carried_to_downstream_agents` | | |
| R-1.31 | Every customer message analysed for ALL useful facts, not just the active question | IMPLEMENTED | `orchestrator.py:487-500` (`bulk_extract` on every rich intake turn); `orchestrator.py:1012` `_apply_extracted_facts` on every specialist turn | `tests/test_casestate_s2.py::test_bulk_runs_every_turn_not_once` | | |
| R-1.32 | The "IVT Geo 600 / För stor skillnad framledning. HP" example preserves category, subtype, brand, entered model, alarm text, alarm family, operating context | PARTIAL | `chat/intake.py:158-200` bulk extractor enumerates all of these | `tests/test_casestate_s2.py::test_bulk_extract_merges_only_into_empty` | | No test uses the owner's own example string. `alarm family/code` (the "HP" suffix) has no dedicated slot — it lands in `error_code` or is lost. |
| R-1.33 | The customer must not be asked for those facts again later | IMPLEMENTED | merge-only-into-empty at every merge site (`orchestrator.py:494`, `:1019`, `:1027`); `_pre_escalate_prompt` (`orchestrator.py:122`) drops the error-code ask when one is known | `tests/test_casestate_s2.py::test_pre_escalate_diag_does_not_re_ask_for_an_error_code_already_known` | S1-NO-REASKING-KNOWN-FACTS | |

## §2 — Intake agent

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-2.01 | Identify the main category | IMPLEMENTED | `casestate.py:13` `REQUIRED_SLOTS[0]`; `intake.py:64` category chips from live `Category` rows | `tests/test_orchestrator.py::test_open_conversation_greets_with_category_chips` | | |
| R-2.02 | Ask for the installation postcode early | IMPLEMENTED | `REQUIRED_SLOTS` puts `postal_code` second | `tests/test_casestate_s2.py::test_postcode_asked_right_after_category` | S2-POSTCODE-EARLY | |
| R-2.03 | Identify the equipment sufficiently for routing | IMPLEMENTED | `casestate.py:85` `has_identity` / `:90` `is_routable` | `tests/test_orchestrator.py::test_supported_case_solves_and_flushes_session` | | |
| R-2.04 | Collect only missing facts | IMPLEMENTED | `casestate.py:94` `next_required_slot` skips filled slots; photo skips brand/model | `tests/test_casestate_s2.py::test_postcode_not_reasked_when_rich_opener_contains_it` | | |
| R-2.05 | Avoid technical troubleshooting during intake | PARTIAL | `kb/seed_prompts.py:65` ("You do NOT diagnose, troubleshoot, or give repair advice") | | | Prompt-only. The intake agent is also structurally constrained — `_intake_step` never calls a specialist — so the practical risk is low, but nothing asserts the rule survives a prompt edit. |
| R-2.06 | Read the complete customer message before asking a question | IMPLEMENTED | `orchestrator.py:487` `intake.looks_rich` → `bulk_extract` before the per-slot extractor | `tests/test_casestate_s2.py::test_bulk_runs_every_turn_not_once` | | |
| R-2.07 | Extract all useful facts from the message | IMPLEMENTED | `chat/intake.py:143` `bulk_extract` (13 fields in one call) | `tests/test_casestate_s2.py::test_bulk_extract_merges_only_into_empty` | | |
| R-2.08 | Never ask for information already in previous messages, known facts, images, OCR or structured case data | IMPLEMENTED | merge-only-into-empty; `_history_parts` carries prior turns + images; OCR writes slots (`orchestrator.py:1905-1919`) | `tests/test_casestate_s2.py::test_postcode_not_reasked_when_rich_opener_contains_it` | S1-NO-REASKING-KNOWN-FACTS | |
| R-2.09 | Ask one clear logical question at a time | IMPLEMENTED | `_intake_step` returns exactly one `q_<slot>` per turn | `tests/test_orchestrator.py::test_open_conversation_greets_with_category_chips` | S2-NO-VERBATIM-REPEAT | |
| R-2.10 | Do not force a fixed questionnaire when sufficient information is already available | IMPLEMENTED | `orchestrator.py:597` `if is_routable(cs): → STATE_ROUTING` short-circuits remaining slots | `tests/test_scenarios/test_n_gap_fixes.py::test_gap2_symptom_opener_lands_category_and_problem_no_apology` | | |
| R-2.11 | Treat an irrelevant answer such as "bb" as off-target | IMPLEMENTED | `intake.py:268` `extract_answer` → `on_target=false`; `looks_rich` keeps a 1-token mash out of the bulk extractor | `tests/test_casestate_s2.py::test_a_genuinely_off_target_answer_still_reports_false` | | |
| R-2.12 | Re-ask the missing question once | IMPLEMENTED | `orchestrator.py:576-583` (`cs["reask"]` → one `t("reask")` prefix re-render) | `tests/test_casestate_s2.py::test_postcode_two_reasks_then_unknown` | S2-NO-VERBATIM-REPEAT | |
| R-2.13 | After two failed attempts record the value as unknown and continue | IMPLEMENTED | `orchestrator.py:579` `if cs["reask"] >= 2: slots[current] = "unknown"` | `tests/test_casestate_s2.py::test_postcode_two_reasks_then_unknown` | | An LLM-call failure is explicitly excluded from the strike count (`orchestrator.py:545`), pinned by `test_a_failed_extractor_call_does_not_charge_a_strike`. |
| R-2.14 | Do not ask for name, telephone, email or full address during technical intake | IMPLEMENTED | `CONTACT_SLOTS` are gathered only in `_escalate_step` (`orchestrator.py:1710`), never by `_intake_step` | `tests/test_orchestrator.py::test_escalation_asks_for_problem_and_error_photo_before_contact` | S2-NO-CONTACT-IN-INTAKE | |
| R-2.15 | Ask for postcode early, directly after the main category is known | IMPLEMENTED | `REQUIRED_SLOTS` order + the rich-opener catch at `orchestrator.py:597-609` | `tests/test_casestate_s2.py::test_postcode_asked_even_when_rich_opener_makes_case_routable` | S2-POSTCODE-EARLY | |
| R-2.16 | Use the owner's suggested postcode wording | IMPLEMENTED | `chat/i18n.py:140` — verbatim match with the letter | `tests/test_i18n.py` | | |
| R-2.17 | Accept Swedish postcodes with or without a space | IMPLEMENTED | `chat/sanitize.py:160` `normalize_postcode` (`_POSTCODE_SE` = 3+optional space+2); fast path `orchestrator.py:493` | `tests/test_casestate_s2.py::test_bare_postcode_is_accepted_deterministically_without_an_llm_call` | | |
| R-2.18 | Normalize to five digits | IMPLEMENTED | `orchestrator.py:442` `_normalise_slot_value` — applied at intake, at bulk-extract merge, and at contact capture (`orchestrator.py:1728`) | `tests/test_casestate_s2.py::test_a_postcode_from_the_bulk_extractor_is_normalised`; `::test_a_postcode_first_given_during_contact_collection_is_normalised` | S12-POSTCODE-NORMALISED | |
| R-2.19 | Validate before service-area checking | IMPLEMENTED | `orchestrator.py:556-561` (undecodable → `on_target=False` → re-ask machinery); `crm/geo.py:191` `geocode_postcode` strips spaces defensively | `tests/test_casestate_s2.py::test_postcode_two_reasks_then_unknown` | | |

## §3 — Model selection and catalog matching

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-3.01 | Never present a short/incomplete model list as the complete manufacturer catalog | IMPLEMENTED | `orchestrator.py:719` `_model_disambig_prompt` always appends an escape chip (`Annan modell` + `Jag vet inte`, or `Ingen av dessa`); `intake.py:_MODEL_CHIP_CAP = 6` with the same two escapes | | | No test asserts the escape chip is always present. |
| R-3.02 | Customer can enter the exact model as free text | IMPLEMENTED | `intake.py:268` `extract_answer("model", …)`; `orchestrator.py:809` `_consume_model_search` | `tests/test_model_named_verbatim.py::test_the_exact_reply_names_the_machine` | | |
| R-3.03 | Customer can search the full catalog for the selected manufacturer | IMPLEMENTED | `orchestrator.py:809` `_consume_model_search` → `kb.identification.suggest_models(vendor=…)` | `tests/test_recognition.py` | | Free-text search scoped to the vendor, not a browsable list. |
| R-3.04 | Customer can upload a nameplate photo | IMPLEMENTED | `static/widget/nordland-widget.js:218` file input; `orchestrator.py:1827` `_run_vision`; `chat/uploads.py` | `tests/test_scenarios/test_e_photo.py` | | |
| R-3.05 | Customer can select "Jag vet inte" | IMPLEMENTED | `intake.py:103` `chip_dontknow`; `intake.py:48` `_DONT_KNOW_RE` (sv+en) | `tests/test_casestate_s2.py::test_dont_know_in_model_search_gives_up_instead_of_searching` | | |
| R-3.06 | Customer can select "Annan modell" | IMPLEMENTED | `intake.py:102` `chip_other_model`; consumed at `orchestrator.py:795` | `tests/test_consult.py::test_budget_disambig_charges_and_gets_plus_one` | | |
| R-3.07 | When subtype is known, filter suggestions by subtype (ground-source/air-to-water/exhaust-air/air-to-air) | IMPLEMENTED | `intake.py:91` `_family_ids(subtype) or _family_ids(category)`; same scoping in `_resolve_machine` (`orchestrator.py:757`) and `_consume_model_search` (`orchestrator.py:836`) | | | No test pins the subtype→candidate narrowing. |
| R-3.08 | A partial model name must not be auto-converted to one exact catalog machine | IMPLEMENTED | `kb/identification.py:24` `exact_machine` requires normalize-equality — "Geo 600" ≠ "Geo 600C" | `tests/test_model_named_verbatim.py::test_the_longest_name_wins_over_a_bare_number` | S3-MODEL-NOT-GUESSED | |
| R-3.09 | Preserve the customer-entered model text | IMPLEMENTED | `casestate.py:18` contract; enforced at every merge site; `_repair_model_slot` restores the longer customer span | `tests/test_casestate_s2.py::test_model_slot_never_overwritten` | S3-MODEL-NOT-GUESSED | |
| R-3.10 | Do not automatically select the first match | IMPLEMENTED | `orchestrator.py:733` `_resolve_machine` — ambiguity pauses with chips, binds only on an explicit tap (`_consume_model_reply`) | `tests/test_model_named_verbatim.py::test_a_repaired_model_binds_instead_of_disambiguating` | S3-MODEL-NOT-GUESSED | |
| R-3.11 | Keep catalog_machine_id = null until clarified | IMPLEMENTED | `cs["machine_id"]` set only in `_bind_confirmed` (`orchestrator.py:708`) | | | |
| R-3.12 | Keep supported = false until clarified | IMPLEMENTED | `casestate.py:113` — `Session.machine` written only when `cs["model_confirmed"]`; route uses `machine and cs["model_confirmed"]` (`orchestrator.py:899`) | `tests/test_orchestrator.py::test_unsupported_brand_becomes_qualified_lead` | | |
| R-3.13 | Ask for the exact suffix, or request a nameplate photo | IMPLEMENTED | `i18n.py:26` `model_disambig`; `orchestrator.py:590-596` one-time photo nudge (`model_photo_nudge`) | | | No test pins the photo nudge. |
| R-3.14 | Only assign supported = true after an exact or clearly verified match | IMPLEMENTED | `_bind_confirmed` is reachable only from `exact_machine` or an explicit chip tap | `tests/test_model_named_verbatim.py::test_text_naming_no_machine_binds_nothing` | | |

## §4 — Router agent

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-4.01 | Classify the category | IMPLEMENTED | `kb/seed_prompts.py:141`; consumed at `orchestrator.py:885` | `tests/test_routing.py` | | |
| R-4.02 | Preserve the real manufacturer | IMPLEMENTED | **at the orchestrator, not the prompt**: `_route` consumes only `severity` and `problem_category` from the router; `slots.brand` is never overwritten by router output | `tests/test_casestate_s2.py::test_bulk_extract_merges_only_into_empty` | S4-BRAND-PRESERVED | The seeded ROUTER prompt (`seed_prompts.py:144`) still says *brand → "…else `other`"*, which contradicts §4. Harmless today only because the field is discarded. |
| R-4.03 | Determine whether an exact local catalog match exists | IMPLEMENTED | `orchestrator.py:733` `_resolve_machine` (deterministic, pre-LLM) | `tests/test_recognition.py` | | The router's own `supported`/`catalog_machine_id` output is ignored; code decides. |
| R-4.04 | Classify the main problem | IMPLEMENTED | `orchestrator.py:888-891` (`ProblemCategory` lookup); `_call_router` fills the enum from seeded rows | `tests/test_routing_v2.py` | | |
| R-4.05 | Assess severity | IMPLEMENTED | `orchestrator.py:886` `cs["severity"] = data.get("severity") or "normal"` | `tests/test_routing.py` | | |
| R-4.06 | The router must not troubleshoot or search manuals | IMPLEMENTED | `_call_router` is JSON-only, `max_output_tokens=200`, no KB/manual in context (`orchestrator.py:946`) | `tests/test_contract_shape.py` | | |
| R-4.07 | Supported categories are heat_pump / water_pump_well / water_filtration / unknown | IMPLEMENTED | `orchestrator.py:636` `SERVICED_FAMILIES`; `seed_prompts.py:141` | `tests/test_general_specialists.py::test_general_role_selection_per_family` | | |
| R-4.08 | supported=true means an exact verified machine exists and the correct manual can be attached | IMPLEMENTED | `orchestrator.py:899-901` → `specialist_mode="manual"` + `machine_pdf_context` | `tests/test_general_specialists.py::test_manual_mode_unchanged_uses_specialist` | | |
| R-4.09 | supported=false means only that no exact local match exists | IMPLEMENTED | `orchestrator.py:902` `elif _serviced_category(cs): specialist_mode="general"` | `tests/test_general_specialists.py::test_general_role_selection_per_family` | | |
| R-4.10 | supported=false must NOT mean Nordland does not service the equipment | IMPLEMENTED | same three-way route; every general prompt states it verbatim (`seed_prompts.py:370`, `:580`, `:604`, `:627`) | `tests/test_general_specialists.py::test_water_scenario_runs_under_water_pump_specialist` | S9-NO-REFER-AWAY | |
| R-4.11 | Preserve known manufacturers not in the catalog (NIBE, CTC, Thermia, Grundfos, Callidus) | IMPLEMENTED | `intake.py:147` `_brand_allowed` = chips ∪ all active `Vendor` rows; unlisted real brands kept verbatim (`intake.py:227`) | `tests/test_casestate_s2.py::test_bulk_extract_merges_only_into_empty` | S4-BRAND-PRESERVED | |
| R-4.12 | Do not replace known non-catalog brands with "other" | IMPLEMENTED | `intake.py:225` `if b and b.lower() != "other"`; extractor branch `intake.py:322` | | S4-BRAND-PRESERVED | The conformance rule's `KNOWN_BRANDS` list is hard-coded to 13 brands, so a real brand outside it (Nilan, Jäspi, Vaillant, Danfoss…) is never checked. PARTIAL as a *detector*. |
| R-4.13 | When supported=false, preserve the manufacturer | IMPLEMENTED | `slots.brand` untouched by routing; `render_kwargs["brand"]` (`orchestrator.py:1222`) | `tests/test_general_specialists.py::test_heat_pump_nibe_runs_under_heat_pump_specialist` | | |
| R-4.14 | …preserve the model text | IMPLEMENTED | `render_kwargs["model"]` (`orchestrator.py:1223`) | as above | | |
| R-4.15 | …preserve the equipment subtype | PARTIAL | `slots.subtype` survives in case state and steers `_category_family` | | | Never rendered into a general-specialist prompt (`render_kwargs` has `category`, not `subtype`), so the agent cannot use it. |
| R-4.16 | …preserve all symptoms and alarms | PARTIAL | `error_code` is rendered; `alarm_text`, `readings`, `operating_context` are not | | | Direct consequence of R-1.12/R-1.15/R-1.16. |
| R-4.17 | …route the case to the Intelligent Specialist | IMPLEMENTED | `orchestrator.py:701` `_general_role` → family agent, `intelligent_specialist` fallback | `tests/test_general_specialists.py::test_general_role_unknown_falls_back_to_intelligent_specialist` | | |

## §5 — General knowledge retrieval before manual level

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-5.01 | A retrieval step against the approved general KB runs before requiring an exact machine manual | PARTIAL | `chat/context.py:82` `collect_general_knowledge`, called on every specialist turn (`orchestrator.py:1219`) | `tests/test_rag_corpus.py` | | The retrieval exists, but the shipped corpus (`data/general_knowledge/…json`, 102 entries) is imported with `is_approved=False` (`kb/management/commands/import_general_knowledge.py:161`) and R-5.14 filters on `is_approved=True` — so until the owner approves it, this step returns **nothing** in production. |
| R-5.02 | Heat-pump system-level symptoms covered (no heat, no hot water, pressure, ΔT, flow, circulation, noise, sudden loss, icing/defrost, airflow, air filter) | IMPLEMENTED | corpus: 46 heat-pump entries incl. subtypes | | | Per-symptom coverage is not asserted anywhere; the count is the only evidence. |
| R-5.03 | Water pump/well symptoms covered (11 listed) | PARTIAL | corpus: 15 `water_pump_well` entries | | | 15 entries against 11 named symptoms plus subtypes — thin, and unasserted. |
| R-5.04 | Water filter symptoms covered (11 listed) | PARTIAL | corpus: 15 `water_filtration` entries | | | Same as above. |
| R-5.05 | Retrieval uses category | IMPLEMENTED | `context.py:104-111` `cat_ids`; `semantic.py:164` filter | `tests/test_rag_corpus.py` | | |
| R-5.06 | …subtype | IMPLEMENTED | `semantic.py:171` `applicable_subtypes` filter | `tests/test_rag_corpus.py` | | |
| R-5.07 | …symptoms | PARTIAL | `semantic.py:178` blob includes `keywords` | | | There is no `symptoms` slot to query with (R-1.12); the query is `slots.problem` only. |
| R-5.08 | …problem description | IMPLEMENTED | `context.py:116` `slots.get("problem")` → `rank_general_knowledge(query=…)` | `tests/test_semantic.py` | | |
| R-5.09 | …onset | IMPLEMENTED | `semantic.py:131` `_onset_match` (sudden ↔ sudden, gradual/always ↔ long_term) | `tests/test_rag_corpus.py` | | |
| R-5.10 | …operating context | **MISSING** | — | | | `slots.operating_context` is never passed to `rank_general_knowledge`. |
| R-5.11 | …alarm text | **MISSING** | — | | | `slots.alarm_text` is never passed to retrieval, and no FAQ field indexes alarm wording. |
| R-5.12 | …pressure or temperature observations | **MISSING** | — | | | `slots.readings` is never passed to retrieval. |
| R-5.13 | …checks already completed | PARTIAL | `_previous_checks_block` (`orchestrator.py:1002`) is injected into the *prompt* | `tests/test_casestate_s2.py::test_previous_checks_block_injected_into_prompt` | | Reaches the agent, but does not influence *retrieval* ranking — a check already done can still be the top-ranked snippet. |
| R-5.14 | Only entries marked approved/verified are used | IMPLEMENTED | `semantic.py:163` `FAQEntry.objects.filter(is_approved=True)`; same in `rank_guides` and `collect_knowledge` | `tests/test_faq_approval.py::test_rank_guides_excludes_unapproved_faq_entry`; `::test_collect_knowledge_excludes_unapproved_faq_entry` | | Single boolean — no "approved" vs "verified" distinction as the letter implies. |
| R-5.15 | Knowledge-entry metadata (category, subtype, manufacturer_specific, applicable manufacturers, symptoms, operating context, onset type, safe checks, exclusions, service-required actions, source type, verification status, reviewed date, internal source ID) | PARTIAL | `kb/models.py:155` `FAQEntry` | `tests/test_import_general_knowledge.py` | | Present: category, `applicable_subtypes`, `manufacturer` (FK), `keywords`≈symptoms, `onset_type`, `safe_customer_checks`, `exclusions`, `service_trigger`, `source_type`, `source_id`, `is_approved`. **Absent: `manufacturer_specific` flag, *multiple* applicable manufacturers, operating context, reviewed date.** The letter calls these "suggested", so this is a PARTIAL by design rather than a defect. |
| R-5.16 | Order step 1 — search approved general Nordland knowledge | IMPLEMENTED | `collect_general_knowledge` runs before the model call in both modes | `tests/test_rag_corpus.py` | | |
| R-5.17 | Order step 2 — give one relevant safe customer-level check when knowledge supports it | PARTIAL | `seed_prompts.py:227` ("ONE check per turn"), all general prompts | `tests/test_scenarios/test_k_vent_water.py` | | Prompt-only; nothing in code enforces one-check-per-turn. |
| R-5.18 | Order step 3 — ask for the result when it affects the next step | IMPLEMENTED | `_record_checks_given` marks each as `pending`; next turn's `check_results` resolves it | `tests/test_casestate_s2.py::test_check_memory_accumulates_then_resolves` | | |
| R-5.19 | Order step 4 — load the exact manual when the answer depends on model-specific information | PARTIAL | `orchestrator.py:1230` `machine_pdf_context` | `tests/test_kb.py` | | The manual is loaded **unconditionally** whenever a machine is confirmed, not on demand. Harmless but not what the letter describes. |
| R-5.20 | Order step 5 — if neither source supports a safe action, offer Nordland VVS service | IMPLEMENTED | `orchestrator.py:1300-1325` escalate path | `tests/test_orchestrator.py::test_low_confidence_escalates` | | |
| R-5.21 | General knowledge must not invent an exact alarm-code meaning | PARTIAL | `seed_prompts.py:189` HARD RULE (manual mode); `:381` (general mode) | `tests/test_scenarios/test_c_unsupported.py` | | Prompt-only, in every specialist role. No conformance rule and no code check — the audit flagged exactly this ("§5 anti-invention list" has no rule). |
| R-5.22 | …a menu path | PARTIAL | same HARD RULE blocks | | | Prompt-only. |
| R-5.23 | …a reset sequence | PARTIAL | same HARD RULE blocks | | | Prompt-only. |
| R-5.24 | …a component location | PARTIAL | `seed_prompts.py:189` names "component locations" for the manual only | | | Prompt-only; the general-mode HARD RULE lists codes/menus/limits but **not** component location. |
| R-5.25 | …exact technical limits | PARTIAL | general-mode HARD RULE ("any numeric limit, setpoint, pressure/temperature value") | | | Prompt-only. |
| R-5.26 | …a model-specific maintenance procedure | PARTIAL | `seed_prompts.py:189` lists "model-specific maintenance" as manual-controlled | | | Prompt-only; not restated in the general-mode HARD RULE. |

## §6 — Standard specialist agent

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-6.01 | Used when an exact verified catalog machine and documentation are available | IMPLEMENTED | `orchestrator.py:899` `if machine and cs["model_confirmed"]` | `tests/test_general_specialists.py::test_manual_mode_unchanged_uses_specialist` | | |
| R-6.02 | Source order 1 = exact manufacturer manual for the identified machine | **PARTIAL** | `seed_prompts.py:184-187` lists: 1 brand notes, 2 general knowledge, **3 manual**, 4 FAQ | `tests/test_prompt_contract.py` | | The seeded prompt's numbered order contradicts §6, mitigated (not fixed) by the HARD RULE at `:189` that makes the manual authoritative for codes/menus/limits. See "Owner decisions" — §5 and §6 give opposite orderings. |
| R-6.03 | Source order 2 = approved Nordland internal knowledge | PARTIAL | `context.py:38-48` `collect_knowledge` (vendor notes, `MachineNote`, `BrandNote`) | `tests/test_kb.py` | | Injected, but at prompt priority 1 rather than 2. |
| R-6.04 | Source order 3 = approved general FAQ / troubleshooting knowledge | PARTIAL | `context.py:50-77` FAQ + guides + semantic `rank_guides` | `tests/test_faq_approval.py::test_collect_knowledge_excludes_unapproved_faq_entry` | | Injected at prompt priority 2/4. |
| R-6.05 | The manual controls alarm-code meaning | PARTIAL | `seed_prompts.py:189` HARD RULE | | | Prompt-only. |
| R-6.06 | …menu paths | PARTIAL | same | | | Prompt-only. |
| R-6.07 | …reset procedures | PARTIAL | same | | | Prompt-only. |
| R-6.08 | …normal user settings | PARTIAL | `seed_prompts.py:213-220` ONSET RULES | `tests/test_prompt_contract.py::test_specialists_are_required_to_establish_onset_before_a_comfort_verdict` | | The onset gate is tested; "the manual controls it" is not. |
| R-6.09 | …model-specific maintenance | PARTIAL | `seed_prompts.py:196` (owner-maintenance bullet) | | | Prompt-only. |
| R-6.10 | …component locations | PARTIAL | `seed_prompts.py:189` | | | Prompt-only. |
| R-6.11 | …exact limits | PARTIAL | `seed_prompts.py:189` | | | Prompt-only. |
| R-6.12 | Give one safe relevant check at a time | PARTIAL | `seed_prompts.py:198` ("ideally one check at a time") | | | Prompt-only, and hedged ("ideally"). |
| R-6.13 | Avoid long speculative lists | PARTIAL | `seed_prompts.py:198`; `max_output_tokens` cap (`orchestrator.py:1241`) | | | Prompt-only. |
| R-6.14 | Avoid repeating checks already completed | IMPLEMENTED | `orchestrator.py:1002` `_previous_checks_block` injected every turn with each check's outcome | `tests/test_casestate_s2.py::test_previous_checks_block_injected_into_prompt` | | |
| R-6.15 | Stop when safe customer-level checks are exhausted | IMPLEMENTED | `REPLY_BUDGET=5` / `GENERAL_REPLY_BUDGET=3` → `forced` wrap-up (`orchestrator.py:1217`) | `tests/test_orchestrator.py::test_reply_budget_forces_escalation` | | |
| R-6.16 | Offer Nordland VVS service when professional work is needed | IMPLEMENTED | `guardrails.is_unsafe` veto → escalate (`orchestrator.py:1295`) | `tests/test_orchestrator.py::test_guardrail_vetoes_unsafe_answer` | | |
| R-6.17 | The agent must cover heat pumps, water pumps, wells, pressure systems, water filters and water treatment | IMPLEMENTED | three family agents (`seed_prompts.py:579`, `:603`, `:626`) + `intelligent_specialist` fallback | `tests/test_general_specialists.py::test_general_role_selection_per_family` | | Wells / pressure systems / water treatment have no agent of their own; they ride `water_pump_specialist` / `water_filtration_specialist`. |

## §7 — Customer comfort and normal user settings

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-7.01 | Help with normal user-accessible settings when the manual or approved knowledge supports the action | PARTIAL | `seed_prompts.py:216-220` ONSET RULES (always/gradual branch) | `tests/test_scenarios/test_o_onset_comfort.py::test_specialist_prompt_comfort_rules_present` | | The *prompt text* is asserted; no behavioural test. |
| R-7.02 | Indoor temperature / small documented heating adjustment / heating-curve offset when the manual treats it as a user setting | PARTIAL | `seed_prompts.py:217` | `tests/test_scenarios/test_o_onset_comfort.py::test_specialist_prompt_comfort_rules_present` | | Prompt-text assertion only. |
| R-7.03 | Hot-water mode (eco/normal/comfort) and temporary extra hot water | PARTIAL | `seed_prompts.py:218` | same | | Prompt-text assertion only. |
| R-7.04 | Heating/cooling mode, ordinary schedules, holiday mode, economy/night reduction, air-to-air fan + temperature | PARTIAL | `seed_prompts.py:218-219` | same | | Prompt-text assertion only; "economy/night reduction" is not named in any prompt. |
| R-7.05 | The system must distinguish always-existed/gradual from a sudden change | IMPLEMENTED | `slots.onset` enum; `orchestrator.py:1216` budget clamp; `_CONTRACT_ADDENDA` "onset is unknown" back-fill (`prompts.py:144`) | `tests/test_prompt_contract.py::test_the_onset_ask_actually_reaches_a_rendered_specialist_prompt` | S7-ONSET-ESTABLISHED | The only §7 rule protected against prompt drift. |
| R-7.06 | On an always/gradual complaint a documented normal customer setting may be appropriate | IMPLEMENTED | `orchestrator.py:1216` (no clamp for gradual/always) + prompt branch | `tests/test_scenarios/test_o_onset_comfort.py::test_gradual_onset_keeps_full_budget` | | |
| R-7.07 | Explain what the setting affects | PARTIAL | `seed_prompts.py:219` ("state what it affects") | `tests/test_scenarios/test_o_onset_comfort.py::test_specialist_prompt_comfort_rules_present` | | Prompt-text only. |
| R-7.08 | Note (or ask the customer to note) the original value | PARTIAL | `seed_prompts.py:219` ("note the ORIGINAL value FIRST") | same | | Prompt-text only; the original value is not stored in case state. |
| R-7.09 | Recommend only a small change | PARTIAL | `seed_prompts.py:219` ("ONE small step at a time") | same | | Prompt-text only. |
| R-7.10 | Change one setting at a time | PARTIAL | `seed_prompts.py:219` | same | | Prompt-text only. |
| R-7.11 | Allow time to evaluate the result | PARTIAL | `seed_prompts.py:220` ("EVALUATE the result before the next change") | same | | Prompt-text only. |
| R-7.12 | On a sudden change, do not assume the ordinary setting is the cause | IMPLEMENTED | `orchestrator.py:1216-1218` budget clamp forces look-only then handoff; `_CONTRACT_ADDENDA` onset text | `tests/test_scenarios/test_o_onset_comfort.py::test_sudden_onset_clamps_budget_to_three` | S7-SUDDEN-NOT-A-SETTING | |
| R-7.13 | Do not simply increase the heating curve | PARTIAL | prompt `seed_prompts.py:214`; conformance `RAISE_SETTING` | `tests/test_scenarios/test_o_onset_comfort.py::test_specialist_prompt_sudden_no_settings_compensation` | S7-SUDDEN-NOT-A-SETTING | The detector is narrow: `höj(a|er)? värmekurvan/kurvan` only. **"höj framledningstemperaturen", "öka framledningen", "skruva upp kurvan", "justera kurvan uppåt" all escape it.** |
| R-7.14 | Do not simply increase the hot-water setting | PARTIAL | same | same | S7-SUDDEN-NOT-A-SETTING | `öka\s+(värmekurvan\|kurvan)` **excludes** `varmvattentemperaturen`, so the Swedish "öka varmvattentemperaturen" is not detected at all. |
| R-7.15 | First check alarms, operating mode, schedules, holiday mode, power interruption, system pressure, circulation, electric backup or another verified operational issue | PARTIAL | `prompts.py:150-154` contract addendum enumerates exactly this list | `tests/test_prompt_contract.py::test_specialists_are_required_to_establish_onset_before_a_comfort_verdict` | | The addendum is code-owned (drift-proof), but nothing checks the model actually did the checks. |
| R-7.16 | Offer Nordland VVS service when no clear customer-setting change explains it | IMPLEMENTED | forced wrap-up → escalate (`orchestrator.py:1217`, `:1300`) | `tests/test_scenarios/test_o_onset_comfort.py::test_sudden_onset_clamps_budget_to_three` | | |
| R-7.17 | Only normal user menus are allowed | PARTIAL | prompts (all specialist roles); `guardrails.py:_FORBIDDEN_INSTRUCTION` covers `installatörsmeny` / `serviceläge` | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | Keyword veto covers two of the nine forbidden classes below. |
| R-7.18 | Never guide into installer menus | IMPLEMENTED | `guardrails.py:_FORBIDDEN_INSTRUCTION` `installat[öo]rsmeny\w*` + en forms | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-7.19 | …service menus | PARTIAL | veto has `serviceläge\b` and `(enter\|go into\|access\|unlock) the (installer\|service\|engineer) (menu\|mode)` | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_en` | S7-FORBIDDEN-GUIDANCE | Bare Swedish **`servicemeny`/`servicemenyn` is not in the keyword veto** (only in the conformance rule). |
| R-7.20 | …factory settings | PARTIAL | conformance `fabriksinst[äa]llning` only | | S7-FORBIDDEN-GUIDANCE | Not in `guardrails.py` at all — a live draft saying "återställ till fabriksinställningar" passes the hard veto. |
| R-7.21 | …pump-speed settings | PARTIAL | conformance `pumphastighet` / `pump speed` / `varvtal på pumpen` | | S7-FORBIDDEN-GUIDANCE | Not in the keyword veto; prompt-only at delivery time. |
| R-7.22 | …compressor limits | PARTIAL | conformance `kompressorbegränsning`; veto covers only "open/unscrew the compressor" | | S7-FORBIDDEN-GUIDANCE | Not in the keyword veto as a *setting*. |
| R-7.23 | …electric-backup limits | **MISSING** | — | | | No veto pattern, no conformance rule. Prompt text only (`seed_prompts.py:221` "backup limits"). |
| R-7.24 | …sensor calibration | PARTIAL | conformance `givarkalibrering` / `kalibrera givare` | | S7-FORBIDDEN-GUIDANCE | Not in the keyword veto. |
| R-7.25 | …safety settings | IMPLEMENTED | `guardrails.py` `bypass (the )?(interlock\|safety)`, `disable (the )?safety`, `inaktivera säkerhet\w*`, `koppla förbi` | `tests/test_guardrails.py::test_keyword_veto_catches_forbidden_classes` | S7-FORBIDDEN-GUIDANCE | |
| R-7.26 | …anti-legionella settings | PARTIAL | veto: `legionella (cycle\|treatment\|flush)`; conformance: bare `legionella` | | S7-FORBIDDEN-GUIDANCE | **English-only in the veto.** Swedish "legionellafunktionen", "legionellaskyddet", "legionellaprogrammet" all pass — the exact definite/compound bug class this repo has shipped repeatedly. |
| R-7.27 | …frost-protection settings | PARTIAL | conformance `frysskydds?inst[äa]llning` | | S7-FORBIDDEN-GUIDANCE | Not in the keyword veto. |

## §8 — Sudden fault rule for all service categories

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-8.01 | The sudden-fault principle applies to ALL technical customer-facing specialists | IMPLEMENTED | `orchestrator.py:1216` clamp is mode-independent; ONSET RULES in the manual specialist, `intelligent_specialist` and all three family prompts | `tests/test_scenarios/test_o_onset_comfort.py::test_intelligent_specialist_prompt_has_onset_rules` | | |
| R-8.02 | Heat pumps: a sudden change (heat/hot water/cooling loss, new alarm, noise, pressure change, icing) is treated as a possible technical problem | IMPLEMENTED | budget clamp + prompt branch | `tests/test_scenarios/test_o_onset_comfort.py::test_sudden_onset_clamps_budget_to_three` | S7-SUDDEN-NOT-A-SETTING | |
| R-8.03 | Water pumps/wells: same for no water, pressure loss/fluctuation, frequent starts, continuous running, won't start, air, new leak, new alarm, noise | IMPLEMENTED | same clamp (category-independent) | `tests/test_scenarios/test_k_vent_water.py` | | |
| R-8.04 | Water filters: same for sudden staining, smell/taste, discolouration, hardness, no regeneration, no backwash, low pressure, new alarm, new leak | IMPLEMENTED | same clamp | `tests/test_scenarios/test_k_vent_water.py` | | |
| R-8.05 | Pumps: do not attempt to compensate by changing pressure settings | IMPLEMENTED | `guardrails.py` `adjust the pressure switch`, `(justera\|ställ om\|ändra) (på )?(pressostat\w*\|tryckvakt\w*)` (definite forms covered) | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv`; `::test_the_definite_form_of_a_regulated_noun_is_still_regulated` | S7-FORBIDDEN-GUIDANCE | |
| R-8.06 | Do not instruct the customer to adjust a pressure switch | IMPLEMENTED | as R-8.05 | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-8.07 | …alter pump start or stop pressure | PARTIAL | conformance `start[- ]och stopptryck` / `start/stop pressure` | | S7-FORBIDDEN-GUIDANCE | **No keyword veto pattern.** A draft saying "sänk stopptrycket till 4 bar" is delivered unless the LLM classifier catches it. |
| R-8.08 | …adjust pressure-tank precharge | IMPLEMENTED | `guardrails.py` `(set\|adjust\|change\|charge\|top up\|increase\|reduce) (the )?pre-?charge` + `(ställ in\|justera\|ändra\|fyll på) (förtryck\w*)`; noun `förtryck\w*` | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-8.09 | …bypass pump protection | IMPLEMENTED | `guardrails.py` dry-run/motor-protection bypass, en+sv (`torrkörningsskydd\w*`, `motorskydd\w*`) | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-8.10 | …open a pump controller | IMPLEMENTED | `guardrails.py` `(öppna\|demontera\|ta isär) (hydrofor\w*\|tryckkärl\w*\|trycktank\w*\|pumpstyrning\w*)` | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-8.11 | …lift a well pump | IMPLEMENTED | `guardrails.py` `(dra\|lyft\|hissa\|ta) upp … brunnspump\w*` + en variants | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | Conformance rule is narrower (`lyfta? (upp )?(brunns)?pumpen` requires the definite form). |
| R-8.12 | Filters: do not repeatedly force regeneration | **MISSING** | — | | | No veto pattern, no conformance rule, and no prompt line forbids *repeated* forced regeneration — `water_filtration_specialist` explicitly *allows* "checking the regeneration status". |
| R-8.13 | …do not increase chemical dosing | IMPLEMENTED | `guardrails.py` `(adjust\|set\|change\|increase\|reduce\|tune) (the )?dos(e\|ing…)` + `(justera\|ändra\|ställ in) (på )?(doseringen\|dosering\w*\|doseringspump\w*)` | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | The conformance rule is narrower (`öka doseringen` only — misses "höj doseringen", "öka dosering"). |
| R-8.14 | …do not change installer programming | IMPLEMENTED | installer/service-menu veto (see R-7.18) | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-8.15 | …do not open the control valve | **MISSING** | — | | | Nothing matches "styrventil" / "control valve" / "ventilhuvudet" in `guardrails.py` or `spec_conformance.py`. Prompt text only (`seed_prompts.py:648`). |
| R-8.16 | …do not change internal filter media | IMPLEMENTED | `guardrails.py` `(byt\w*\|fyll\w* på\|ersätt\w*) (ut )?filtermass\w*` — covers "byt filtermassan" | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | The **conformance** rule `byta\s+filtermassa` misses the common imperative "byt filtermassan" — detector-side gap only. |
| R-8.17 | General rule: do not make large setting changes on a sudden unexplained change | IMPLEMENTED | budget clamp + prompt | `tests/test_scenarios/test_o_onset_comfort.py::test_sudden_onset_clamps_budget_to_three` | S7-SUDDEN-NOT-A-SETTING | |
| R-8.18 | …do not continue into professional troubleshooting | IMPLEMENTED | `guardrails.is_unsafe` two-layer veto on every delivered draft (`orchestrator.py:1295`, `:1353`) | `tests/test_orchestrator.py::test_guardrail_vetoes_unsafe_answer` | S7-FORBIDDEN-GUIDANCE | |
| R-8.19 | …offer Nordland VVS service | IMPLEMENTED | `_begin_escalation` (`orchestrator.py:1367`) | `tests/test_scenarios/test_b_escalate.py` | | |

## §9 — Intelligent specialist for unmatched equipment

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-9.01 | Used when no exact local catalog machine or manual is available | IMPLEMENTED | `orchestrator.py:902` `elif _serviced_category(cs)` | `tests/test_general_specialists.py::test_general_role_selection_per_family` | | |
| R-9.02 | Still handles heat pumps (most manufacturers), water pumps, wells, domestic water, filters, water treatment | IMPLEMENTED | three family agents + fallback (`orchestrator.py:668`) | `tests/test_general_specialists.py::test_water_scenario_runs_under_water_pump_specialist` | | |
| R-9.03 | Source priority 1 = approved Nordland general knowledge | IMPLEMENTED | `collect_general_knowledge` is source #1 in every general prompt (`seed_prompts.py:374`) | `tests/test_rag_corpus.py` | | |
| R-9.04 | Source priority 2 = exact official manufacturer user manual | **MISSING** | — | | | `consult_web` searches official domains for *identification/specs/controls* and is explicitly forbidden from repair procedures (`chat/consult.py:104`). There is no path that retrieves and reads an official user manual for an unmatched unit. |
| R-9.05 | Source priority 3 = official manufacturer product page / datasheet | IMPLEMENTED | `chat/consult.py:159` `consult_web` | `tests/test_consult.py::test_web_consult_flow_digest_injected` | | |
| R-9.06 | Source priority 4 = official manufacturer support information | IMPLEMENTED | same (allowlist is domain-level, so support pages on an allowlisted domain qualify) | `tests/test_consult.py::test_seed_sets_official_domains` | | |
| R-9.07 | For non-IVT products, web research limited to official manufacturer sites / official national sites / official importers | IMPLEMENTED | `consult.py:124` `_allowlist` from `Vendor.official_domains`; `consult.py:135` `_host_allowed` filters every grounding chunk in Python before anything reaches the digest | `tests/test_consult.py::test_web_lookalike_domain_rejected`; `::test_web_mixed_chunks_only_whitelisted_in_material` | | Strongest-enforced rule in the spec. |
| R-9.08 | Never use forums, social media, YouTube, repair blogs, retailer articles, anonymous manuals or uncertain documents | IMPLEMENTED | same allowlist (deny-by-default); plus the laundering guard at `consult.py:186` that drops the search summary when any chunk failed the filter | `tests/test_consult.py::test_web_all_chunks_non_whitelisted_no_digest`; `::test_web_all_whitelisted_chunks_keep_search_summary` | | |
| R-9.09 | An official product page may be used for identification, intended use, basic specs, controller type and normal customer controls | PARTIAL | `consult.py:104` `_WEB_SYSTEM` states exactly this scope | `tests/test_consult.py::test_consult_web_in_general_prompts_only` | | Prompt-side restriction inside the digest agent; the scope list itself is not asserted. |
| R-9.10 | A marketing product page must not be the sole basis for repair instructions | PARTIAL | `_WEB_SYSTEM`: "NEVER state a repair or service procedure sourced from the web"; contract addendum `prompts.py:161` | `tests/test_prompt_contract.py::test_manual_specialist_never_offered_consult_web` | | Prompt-only. **Nothing in code prevents a web-derived fact from setting `in_docs=true`** — the prompt says it must not, and `orchestrator.py:1286` only caps confidence when `in_docs` is already `false`. |
| R-9.11 | Only simple customer-level checks may be provided | PARTIAL | general prompts' safe envelope (`seed_prompts.py:397`) + `GENERAL_REPLY_BUDGET=3` | `tests/test_general_specialists.py::test_water_scenario_runs_under_water_pump_specialist` | | |
| R-9.12 | If no verified safe action is available, or safe checks don't solve it, offer Nordland VVS service | IMPLEMENTED | `orchestrator.py:1300-1325`; general budget 3 | `tests/test_orchestrator.py::test_reply_budget_forces_escalation` | | |
| R-9.13 | Do not refer elsewhere solely because it is not IVT | IMPLEMENTED | `_serviced_category` routes to a general agent; every general prompt states "supported=false NEVER means we don't service it" | `tests/test_general_specialists.py::test_heat_pump_nibe_runs_under_heat_pump_specialist` | S9-NO-REFER-AWAY | |
| R-9.14 | …solely because the manufacturer is not in the local catalog | IMPLEMENTED | as R-9.13 | same | S9-NO-REFER-AWAY | |
| R-9.15 | …solely because the manual is missing locally | IMPLEMENTED | as R-9.13 | same | S9-NO-REFER-AWAY | |
| R-9.16 | …solely because Nordland VVS did not originally install it | PARTIAL | no code links installer to scope; general routing ignores `installer` | | S9-NO-REFER-AWAY | The conformance regex is narrow: `kontakta (din )?(återförsäljare\|tillverkaren\|leverantören)` — **"kontakta NIBE", "kontakta din installatör", "hör av dig till märkets serviceverkstad" all escape it.** |

## §10 — Safety classifier

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-10.01 | The Safety Classifier remains a final safety backstop | IMPLEMENTED | `chat/guardrails.py:159` `is_unsafe` = keyword veto (authoritative) + LLM classifier; run on every delivered draft in both `_specialist_step` and `_unsupported_step` | `tests/test_guardrails.py::test_keyword_veto_overrides_llm`; `tests/test_orchestrator.py::test_guardrail_vetoes_unsafe_answer` | | |
| R-10.02 | Covers heat pumps, water pumps, wells, pressure systems, filters and water-treatment equipment | IMPLEMENTED | `guardrails.py` S4 water-domain block; `seed_prompts.py:690-697` | `tests/test_guardrails.py::test_safety_prompt_covers_water_domain` | | |
| R-10.03 | Flags internal electrical work | IMPLEMENTED | `_FORBIDDEN_INSTRUCTION` `rewire`, electrical/control/service panel, `fuse box`, `terminal block`, `live wire`, `elskåp\w*`, `kopplingsplint\w*`, `strömförande` | `tests/test_guardrails.py::test_keyword_veto_catches_forbidden_classes` | S7-FORBIDDEN-GUIDANCE | |
| R-10.04 | …refrigerant work | IMPLEMENTED | `recharge`, `top up (gas\|refrigerant)`, `fylla på köldmedi\w*`; noun `köldmedi\w*` + manipulation cue | `tests/test_guardrails.py::test_keyword_still_blocks_noun_with_manipulation_cue_swedish` | S7-FORBIDDEN-GUIDANCE | Definite/compound forms covered (`köldmediet`, `köldmedieläckage`). |
| R-10.05 | …expansion vessels | IMPLEMENTED | noun `expansionskärl\w*` / `expansion vessel` + cue | `tests/test_guardrails.py::test_keyword_allows_safe_domain_mention_swedish` | S7-FORBIDDEN-GUIDANCE | Mention-safe by design (§10 allows naming it). |
| R-10.06 | …safety valves | IMPLEMENTED | noun `säkerhetsventil\w*` / `safety valve` / `relief valve` + cue | `tests/test_guardrails.py::test_the_definite_form_of_a_regulated_noun_is_still_regulated` | S7-FORBIDDEN-GUIDANCE | |
| R-10.07 | …pressure-tank precharge | IMPLEMENTED | see R-8.08 | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-10.08 | …pressure-switch adjustment | IMPLEMENTED | see R-8.06 | same | S7-FORBIDDEN-GUIDANCE | |
| R-10.09 | …pulling a well pump | IMPLEMENTED | see R-8.11 | same | S7-FORBIDDEN-GUIDANCE | |
| R-10.10 | …opening pump controllers | IMPLEMENTED | see R-8.10 | same | S7-FORBIDDEN-GUIDANCE | |
| R-10.11 | …opening pressurized filter tanks | IMPLEMENTED | `hydrofor\w*\|tryckkärl\w*\|trycktank\w*` open/dismantle patterns | same | S7-FORBIDDEN-GUIDANCE | |
| R-10.12 | …changing filter media in pressure vessels | IMPLEMENTED | see R-8.16 | same | S7-FORBIDDEN-GUIDANCE | |
| R-10.13 | …internal control-valve work | **MISSING** | — | | | See R-8.15. Only the SAFETY *prompt* mentions "opening or dismantling the control valve"; no keyword pattern, no conformance rule. |
| R-10.14 | …chemical dosing changes | IMPLEMENTED | see R-8.13 | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_sv` | S7-FORBIDDEN-GUIDANCE | |
| R-10.15 | …bypassing safety devices | IMPLEMENTED | `bypass (the )?(interlock\|safety)`, `disable (the )?safety`, `koppla förbi`, `förbikoppl\w*` | `tests/test_guardrails.py::test_keyword_veto_catches_forbidden_classes` | S7-FORBIDDEN-GUIDANCE | |
| R-10.16 | …installer/service menus | PARTIAL | see R-7.18/R-7.19 | `tests/test_guardrails.py::test_water_domain_instructions_vetoed_en` | S7-FORBIDDEN-GUIDANCE | Bare `servicemeny` gap. |
| R-10.17 | …other professional tasks | PARTIAL | LLM classifier prompt (`seed_prompts.py:699` "Any other licensed/professional service work") | `tests/test_guardrails.py::test_is_unsafe_consults_llm_when_no_keyword` | | Catch-all lives only in the classifier prompt; `classify_unsafe` fails **open** on any exception (`guardrails.py:154` returns `False, ""`). |
| R-10.18 | Allows reading a display or gauge | IMPLEMENTED | look-only verbs deliberately absent from `_MANIP_CUE` (`guardrails.py:127`) | `tests/test_guardrails.py::test_keyword_allows_safe_envelope` | | |
| R-10.19 | …checking visible leakage | IMPLEMENTED | same | `tests/test_guardrails.py::test_keyword_allows_safe_envelope` | | |
| R-10.20 | …checking external normal controls | IMPLEMENTED | same; `seed_prompts.py:710` | `tests/test_guardrails.py::test_keyword_allows_safe_domain_mention` | | |
| R-10.21 | …cleaning user-accessible air filters | IMPLEMENTED | the deliberate front-panel carve-out at `guardrails.py:22-27`; `seed_prompts.py:717-723` | `tests/test_guardrails.py::test_ordinary_customer_parts_are_not_regulated` | | |
| R-10.22 | …checking salt level | IMPLEMENTED | `seed_prompts.py:724` | `tests/test_guardrails.py::test_fyll_pa_salt_cannot_veto` | | |
| R-10.23 | …adding approved salt | IMPLEMENTED | same | `tests/test_guardrails.py::test_fyll_pa_salt_cannot_veto` | | |
| R-10.24 | …checking normal regeneration status | PARTIAL | `seed_prompts.py:726` (classifier prompt allow-list) | | | Prompt-only; no keyword-side assertion. |
| R-10.25 | …following a verified user-serviceable filter procedure | IMPLEMENTED | `guardrails.py:22-27` carve-out + `seed_prompts.py:717` | `tests/test_guardrails.py::test_ordinary_customer_parts_are_not_regulated` | | |
| R-10.26 | Inject FAQ remains DISABLED for the Safety Classifier | PARTIAL | Effectively true: `prompts.render("safety", …)` passes no FAQ, and `context.collect_knowledge` reads `config_for("specialist")` only (`chat/context.py:50`) | | | `AgentPrompt.inject_faq` **defaults to `True`** (`kb/models.py:289`) and `seed_kb` never sets it False, so the dashboard shows "Inject FAQ: on" for the safety role. The flag is inert but contradicts the config surface, and nothing pins it. |

## §11 — Session summarizer

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-11.01 | The summarizer must not troubleshoot or add technical facts | PARTIAL | `seed_prompts.py:662` DETERMINISTIC RULES ("State only what is in the transcript. Never invent…") | | | Prompt-only. |
| R-11.02 | Summarize equipment identification | IMPLEMENTED | `seed_prompts.py:653` | `tests/test_casestate_s2.py::test_summarizer_prompt_covers_new_sections` | | |
| R-11.03 | …problem and symptoms | IMPLEMENTED | `seed_prompts.py:656` | same | | |
| R-11.04 | …severity and reason | IMPLEMENTED | `seed_prompts.py:658`, `:665` | same | | |
| R-11.05 | …safe checks completed or suggested | IMPLEMENTED | `seed_prompts.py:658` | same | | |
| R-11.06 | …results | IMPLEMENTED | `seed_prompts.py:659` ("helped / didn't help / refused / awaiting") | same | | |
| R-11.07 | …recommended next action | IMPLEMENTED | `seed_prompts.py:660` | same | | |
| R-11.08 | …contact, consent, form and booking status | IMPLEMENTED | `seed_prompts.py:660-661` | same | | |
| R-11.09 | Must state when the exact model is missing | IMPLEMENTED | `seed_prompts.py:664` literal "not captured" + the closing "Missing:" sentence | `tests/test_spec_conformance.py::test_lead_summary_hiding_a_missing_model_is_flagged` | S11-SUMMARY-STATES-GAPS | |
| R-11.10 | …no error code captured | PARTIAL | same "Missing:" mechanism | | S11-SUMMARY-STATES-GAPS | The conformance rule only fires when the **model** is missing (`spec_conformance.py:398`); a missing error code is never checked. |
| R-11.11 | …contact details not captured | PARTIAL | `seed_prompts.py:666` | | | Same — not checked by any rule. |
| R-11.12 | …consent not captured | PARTIAL | `seed_prompts.py:666` | | | Same. |
| R-11.13 | …booking not confirmed | PARTIAL | `seed_prompts.py:667` | | | Same. |
| R-11.14 | Must not treat a shown form button as a submitted service request | IMPLEMENTED | `seed_prompts.py:667` literal sentence; data model keeps `Session.form_shown` separate from `booking_requested` | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_post_lead_thanks_and_tracking` | S13-FORM-NOT-A-BOOKING | |
| R-11.15 | Inject FAQ remains DISABLED for the Session Summarizer | PARTIAL | Effectively true (`crm/leads.py:17` renders the summarizer with transcript only) | | | Same inert-flag problem as R-10.26. |

## §12 — Postcode and service-area control

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-12.01 | Postcode requested early, after the main category is known | IMPLEMENTED | see R-2.15 | `tests/test_casestate_s2.py::test_postcode_asked_right_after_category` | S2-POSTCODE-EARLY | |
| R-12.02 | Service area ≈ coastal corridor Örnsköldsvik→Uppsala, ~50 km inland, extensions to southern Sollefteå and Ånge | IMPLEMENTED | `docs/service-areas/initial-polygons.geojson`; `crm/management/commands/seed_service_areas.py`; reference cities `crm/geo.py:290` | `tests/test_geo.py::test_seed_service_areas_idempotent`; `::test_seed_service_areas_no_bbox_warnings` | | |
| R-12.03 | Service area controlled through editable geographic polygons | IMPLEMENTED | `crm.ServiceArea.polygon` JSONField; `dashboard/views.py:446` add / `:492` delete / `:502` toggle | `tests/test_service_area_dashboard.py::test_service_area_add_valid_polygon` | | |
| R-12.04 | Process step 1 — normalize the Swedish postcode | IMPLEMENTED | `sanitize.normalize_postcode`; `geo.geocode_postcode` strips spaces again | `tests/test_casestate_s2.py::test_a_postcode_from_the_bulk_extractor_is_normalised` | S12-POSTCODE-NORMALISED | |
| R-12.05 | Step 2 — geocode the postcode to coordinates | IMPLEMENTED | `crm/geo.py:191` `geocode_postcode` → `crm.PostcodeArea` (offline GeoNames table) | `tests/test_geo.py::test_import_postcodes_fixture_idempotent` | | |
| R-12.06 | Step 3 — test the coordinate against the configured polygons | IMPLEMENTED | `crm/geo.py:27` `point_in_ring` / `:57` `point_in_polygon` (holes honoured) / `:88` `distance_to_edge_km` | `tests/test_geo.py::test_point_in_polygon_with_hole`; `::test_point_in_multipolygon` | | |
| R-12.07 | Step 4 — return inside_area / border_review / outside_area | IMPLEMENTED | `crm/geo.py:206` `check_service_area` | `tests/test_geo.py::test_inside_area`; `::test_border_review_for_extension_area`; `::test_outside_area` | | Plus two extra statuses the letter doesn't name: `unknown_postcode`, `not_configured`. |
| R-12.08 | The polygon is the main source of truth | IMPLEMENTED | `check_service_area` decides purely on polygon containment/distance; the postcode is only a coordinate lookup | `tests/test_geo.py::test_inside_area` | | |
| R-12.09 | Postcode checking is preliminary | IMPLEMENTED | `orchestrator.py:639` `_refresh_service_area` explicitly "NEVER gates troubleshooting"; enforcement only at lead time (`_service_area_gate`) | `tests/test_scenarios/test_p_service_area.py::test_dormant_geo_behaves_as_before` | | |
| R-12.10 | The full installation address receives the final check when the customer opens or submits the website form | **MISSING** | — | | | There is no address geocoder anywhere. `crm/geo.py` geocodes postcodes only; the prefill endpoint (`chat/views.py:157`) returns the address but runs **no** area check on it, and the dashboard test box accepts a postcode only. |
| R-12.11 | Border cases may submit a service request for manual review | IMPLEMENTED | `orchestrator.py:1412` border/unknown → proceed + `coverage_confirm` note | `tests/test_scenarios/test_p_service_area.py::test_border_area_adds_coverage_line` | | |
| R-12.12 | Admin can DRAW polygons | IMPLEMENTED | `static/vendor/leaflet.draw.js` + `static/dashboard/js/service-area-map.js`; editor context `dashboard/views.py:436` | `tests/test_service_area_dashboard.py::test_service_area_page_renders` | | |
| R-12.13 | Admin can EDIT polygons | **MISSING** | — | | | `dashboard/urls.py:36-43` exposes add / delete / toggle / export / test / coverage / places — **no edit route**. Changing a shape means delete + re-add, which loses the row and its category assignments. |
| R-12.14 | Admin can DELETE polygons | IMPLEMENTED | `dashboard/views.py:492` | `tests/test_service_area_dashboard.py::test_service_area_toggle_and_delete` | | |
| R-12.15 | Admin can ACTIVATE/DEACTIVATE polygons | IMPLEMENTED | `dashboard/views.py:502` `service_area_toggle` | `tests/test_service_area_dashboard.py::test_service_area_toggle_and_delete` | | |
| R-12.16 | Admin can assign polygons to one or more service categories | IMPLEMENTED | `dashboard/views.py:476` `area.categories.set(cat_ids)`; `crm/geo.py:255` `models_q_categories` | `tests/test_geo.py::test_category_scoping`; `::test_category_scoping_empty_applies_to_all` | | Assignment is only possible **at creation** — see R-12.13. |
| R-12.17 | Admin can import GeoJSON | IMPLEMENTED | `dashboard/views.py:463` textarea → `geo.clean_polygon` (Feature / FeatureCollection / bare geometry) | `tests/test_geo.py::test_clean_polygon_unwraps_feature_collection`; `tests/test_service_area_dashboard.py::test_service_area_add_rejects_bad_geojson` | | |
| R-12.18 | Admin can export GeoJSON | IMPLEMENTED | `dashboard/views.py:513` `service_area_export` | `tests/test_service_area_dashboard.py::test_service_area_export_returns_geojson` | | |
| R-12.19 | Admin can test an area against a postcode | IMPLEMENTED | `dashboard/views.py:602` `service_area_test` (`ignore_enabled=True`) | `tests/test_service_area_dashboard.py::test_postcode_test_box_works_even_when_disabled` | | |
| R-12.20 | …or against a full address | **MISSING** | — | | | Consequence of R-12.10. |
| R-12.21 | Different service areas possible for heat pumps, water pumps, wells and water filters | PARTIAL | `ServiceArea.categories` M2M over `kb.Category` | `tests/test_geo.py::test_category_scoping` | | Three families exist, not four: **wells are not separable from water pumps** (`water_pump_well` is one category). |
| R-12.22 | Previous installations by Nordland VVS / Bylunds VVS / Nordborr i Sundsvall accepted even outside the polygon | IMPLEMENTED | `crm/models.py:251` `_default_previous_installers` (exact three names); `crm/geo.py:301` `check_with_override` | `tests/test_geo.py::test_check_with_override_upgrades_outside_to_inside`; `tests/test_scenarios/test_p_service_area.py::test_outside_with_listed_installer_upgrades_to_inside` | | No conformance rule (audit finding confirmed). |
| R-12.23 | The previous-installation override is checked BEFORE finally rejecting an outside-area case | IMPLEMENTED | `orchestrator.py:1400-1409` — override runs, then the installer is asked once, then decline | `tests/test_scenarios/test_p_service_area.py::test_outside_no_installer_declines_no_lead_no_form`; `::test_outside_direct_no_declines` | | |

## §13 — Website form integration

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-13.01 | The chatbot connects to the existing forms on the Nordland VVS website | IMPLEMENTED | `crm.FormButton` rows → chip with URL; `static/prefill/nordland-prefill.js` reads `?nl_case=` and fills the live form | `tests/test_prefill.py::test_build_form_url_appends_token_param` | | |
| R-13.02 | Check which form plugin the site uses and recommend the best solution | IMPLEMENTED | `docs/plans/2026-07-13-prefill-install.md`; chosen approach = signed token + read-only REST snapshot + drop-in JS | | | Advisory requirement; a concrete recommendation shipped. |
| R-13.03 | Avoid putting sensitive customer information in public URL parameters | IMPLEMENTED | `chat/prefill.py:18` signed `?nl_case=<token>` (30-min TTL); the payload is fetched server-side | `tests/test_prefill.py::test_read_prefill_token_rejects_expired`; `::test_read_prefill_token_rejects_bad_signature` | | Contact block is withheld unless `consent_to_contact` (`chat/views.py:199`), pinned by `test_prefill_endpoint_omits_contact_without_consent`. |
| R-13.04 | Transfer: category | IMPLEMENTED | `chat/views.py:182` | `tests/test_prefill.py::test_prefill_endpoint_returns_technical_fields` | | |
| R-13.05 | …subtype | **MISSING** | `chat/views.py:183` sends `session.problem_category.label` under the key `"subtype"` | `tests/test_prefill.py::test_prefill_endpoint_returns_technical_fields` | | **Wrong field.** `problem_category` is the *fault* classification ("no_heat"), not the equipment subtype. The real value (`slots.subtype`, e.g. `liquid_to_water`) is never sent. The test asserts the key exists, not that it means what §13 says. |
| R-13.06 | …brand | IMPLEMENTED | `chat/views.py:184` | same | | |
| R-13.07 | …model | IMPLEMENTED | `chat/views.py:185` | same | | |
| R-13.08 | …alarm code | IMPLEMENTED | `chat/views.py:186` | same | | |
| R-13.09 | …alarm text | IMPLEMENTED | `chat/views.py:187` (from `case_state.slots`) | `tests/test_prefill.py::test_prefill_endpoint_derives_problem_and_alarm_from_case_state` | | |
| R-13.10 | …problem description | IMPLEMENTED | `chat/views.py:188` | same | | |
| R-13.11 | …symptoms | **MISSING** | — | | | No symptoms field exists (R-1.12). |
| R-13.12 | …postcode | IMPLEMENTED | `chat/views.py:189` | `tests/test_prefill.py::test_prefill_endpoint_returns_technical_fields` | | |
| R-13.13 | …photos | **MISSING** | — | | | The prefill payload carries no image references. Photos reach the CRM (`crm/leads.py:64`) but never the website form. |
| R-13.14 | …OCR | **MISSING** | — | | | `slots.ocr_text` is not in the prefill payload. |
| R-13.15 | …checks already completed | **MISSING** | — | | | `Session.troubleshooting_performed` exists and rides the lead, but is not in the prefill payload — so the office form shows none of the work already done. |
| R-13.16 | The customer then adds name, telephone, email and full installation address | IMPLEMENTED | `casestate.py:21` `CONTACT_SLOTS`; prefill returns them only with consent so the form can pre-fill a returning customer | `tests/test_prefill.py::test_prefill_endpoint_includes_contact_with_consent`; `tests/test_contact_address.py` | | |
| R-13.17 | Backend-controlled button: heat_pump → heat-pump service form | IMPLEMENTED | `crm/models.py:313` `FormButton.CATEGORY`; `crm/form_buttons.py:34` `form_button_for` | `tests/test_scenarios/test_q_form_chip.py::test_form_chip_shape_for_category`; `tests/test_forms_dashboard.py::test_forms_page_creates_the_4_fixed_rows_on_get` | | |
| R-13.18 | …water_pump_well → water-pump/well form | IMPLEMENTED | same | `tests/test_scenarios/test_q_form_chip.py::test_form_chip_resolves_subtype_leaf_to_family` | | |
| R-13.19 | …water_filtration → water-filter form | IMPLEMENTED | same | `tests/test_scenarios/test_q_form_chip.py::test_form_chip_shape_for_category` | | |
| R-13.20 | …quote_request → quotation form | IMPLEMENTED | `form_buttons.py:41` fallback row | `tests/test_scenarios/test_q_form_chip.py::test_form_chip_falls_back_to_quote_request` | | |
| R-13.21 | Show the button when decision = "escalate" | **MISSING** | `orchestrator.py:1308` sets `_emit_form` on the escalate path **only** when `_wants_form(user_text)` | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_explicit_ask` (covers the explicit-ask case only) | | A customer who is escalated but declines consent, or drops out during contact collection, is **never offered the website form**. `_unsupported_step` and the routing-rule escalate path set `_emit_form` at all. |
| R-13.22 | …when report.service_recommended = true | **MISSING** | — | | | `service_recommended` is written to the report/Session but is never a chip trigger. |
| R-13.23 | …when severity = "service" | IMPLEMENTED | `orchestrator.py:1323` `cs["_emit_form"] = _wants_form(user_text) or cs.get("severity") == "service"` | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_solve_service_severity` | | Only on the **solve** path; a `severity="service"` case that escalates gets no chip. |
| R-13.24 | …when the customer directly asks to book service or request a quotation | IMPLEMENTED | `orchestrator.py:209` `_FORM_ASK` / `:215` `_wants_form` | `tests/test_scenarios/test_q_form_chip.py::test_emission_on_explicit_ask` | | |
| R-13.25 | The AI must not invent URLs | IMPLEMENTED | `form_buttons.py:34` — a chip URL can only come from an active `FormButton` row; `form_chip_for` returns None without one | `tests/test_scenarios/test_q_form_chip.py::test_no_button_no_chip` | | Nothing stops the *model* from writing a URL inside `answer_to_customer`; no guardrail and no conformance rule checks for that (audit finding confirmed). |
| R-13.26 | Form URLs are configured in the backend | IMPLEMENTED | `crm.FormButton`; dashboard editor `dashboard/views.py` + `tests/test_forms_dashboard.py` | `tests/test_forms_dashboard.py::test_forms_save_updates_all_rows` | | |
| R-13.27 | Showing the button does not mean the form is submitted or a booking confirmed | IMPLEMENTED | `report.form_status = "shown"` (`orchestrator.py:244`) distinct from `booking_requested`; `NO_BOOKING` in every customer-facing prompt + code-owned addendum (`prompts.py:113`) | `tests/test_prompt_contract.py::test_contract_survives_a_prompt_the_owner_rewrote` | S13-FORM-NOT-A-BOOKING | Undercut by `i18n.py:229` `outside_area_decline` — "så jag kan inte **boka ett teknikerbesök** där" states the bot books visits. |

## §14 — Responsibility and next step

| ID | Requirement | Status | Code | Test | Conformance | Note |
|---|---|---|---|---|---|---|
| R-14.01 | The owner continues reviewing and adding knowledge, guides, manuals, machine notes and verified KB content | NOT-CHECKABLE | — | | | Human process. The *surface* exists: `dashboard/knowledge.py`, `kb/management/commands/import_kb.py`, `ingest_pdf.py`, `import_general_knowledge.py`, the FAQ approval queue. |
| R-14.02 | Implement the listed technical solutions (case state, multi-fact extraction, model matching, off-target answers, routing, general-knowledge retrieval, model UI, service area, postcode, form integration, buttons, prefill) | PARTIAL | all twelve have shipped code; see the per-section rows above | | | Rolls up every gap in this document. |
| R-14.03 | Flag when a schema or contract needs to change so agent outputs and backend stay aligned | IMPLEMENTED | `chat/prompts.py:97` `_CONTRACT_ADDENDA` + `safety_addendum` — code-owned contract keys back-filled into any prompt body that predates them | `tests/test_prompt_contract.py::test_every_contract_key_the_backend_reads_is_declared_to_the_role` | | The strongest structural answer to the letter's last paragraph. |

---

# 1. Counts

## By status

Counted programmatically from the tables above, not estimated.

| Status | Count | Share |
|---|---:|---:|
| IMPLEMENTED | 193 | 67% |
| PARTIAL | 73 | 25% |
| MISSING | 20 | 7% |
| NOT-CHECKABLE | 1 | <1% |
| **Total** | **287** | |

Of the 193 IMPLEMENTED, **9 have an empty test cell** — code exists and was read, but nothing
pins it: R-1.07 (catalog-match confidence), R-1.10 (alarm text), R-3.01 (escape chip always
offered), R-3.07 (subtype narrows candidates), R-3.11 (`catalog_machine_id` stays null),
R-3.13 (photo nudge), R-4.12 (brand never squashed to "other"), R-5.02 (heat-pump symptom
coverage), R-13.02 (form-plugin recommendation). A further large block is IMPLEMENTED with a
test that pins the *prompt text* rather than the behaviour — those are called out in Tier D.

## By section

| § | Title | Total | IMPL | PARTIAL | MISSING | N/C |
|---|---|---:|---:|---:|---:|---:|
| 0 | Scope & top-level policy | 5 | 3 | 2 | 0 | 0 |
| 1 | Shared case state | 33 | 26 | 5 | 2 | 0 |
| 2 | Intake agent | 19 | 18 | 1 | 0 | 0 |
| 3 | Model selection & catalog | 14 | 14 | 0 | 0 | 0 |
| 4 | Router agent | 17 | 15 | 2 | 0 | 0 |
| 5 | General-knowledge retrieval | 26 | 9 | 14 | 3 | 0 |
| 6 | Standard specialist | 17 | 5 | 12 | 0 | 0 |
| 7 | Comfort & user settings | 27 | 6 | 20 | 1 | 0 |
| 8 | Sudden-fault rule | 19 | 16 | 1 | 2 | 0 |
| 9 | Intelligent specialist | 16 | 11 | 4 | 1 | 0 |
| 10 | Safety classifier | 26 | 21 | 4 | 1 | 0 |
| 11 | Session summarizer | 15 | 9 | 6 | 0 | 0 |
| 12 | Postcode & service area | 23 | 19 | 1 | 3 | 0 |
| 13 | Website form integration | 27 | 20 | 0 | 7 | 0 |
| 14 | Responsibility & next step | 3 | 1 | 1 | 0 | 1 |

The shape of the result: **§2, §3, §12 and §13 are essentially built** (intake, model matching,
service area, form plumbing all have code and tests). **§5, §6 and §7 are the weak sections** —
46 of their 70 requirements are PARTIAL, and almost all of those are prompt-text-only rules with
no drift protection (Tier D). That is the single largest structural risk in the audit: the
letter's knowledge-and-settings discipline lives in editable text, not in code.

**Conformance-rule note.** `tools/eval/spec_conformance.py` defines **15** rules, not 16:
`S7-FORBIDDEN-GUIDANCE`, `S7-SUDDEN-NOT-A-SETTING`, `S2-NO-CONTACT-IN-INTAKE`,
`S2-POSTCODE-EARLY`, `S4-BRAND-PRESERVED`, `S9-NO-REFER-AWAY`, `S3-MODEL-NOT-GUESSED`,
`S13-FORM-NOT-A-BOOKING`, `S2-NO-INTERNAL-TAGS`, `S2-NO-VERBATIM-REPEAT`,
`S1-NO-REASKING-KNOWN-FACTS`, `S7-ONSET-ESTABLISHED`, `S12-POSTCODE-NORMALISED`,
`S3-MODEL-IS-NOT-AN-ALARM`, `S11-SUMMARY-STATES-GAPS`. Sections **5, 6, 12 and 14 have no
conformance rule of their own**, and §10's coverage is entirely borrowed from
`S7-FORBIDDEN-GUIDANCE`. Counting rows with an empty conformance cell: **213 of 287
requirements (74%) are unobservable in live transcripts** — the eval harness can confirm a
conversation broke the spec only for the 23% the 15 rules reach.

---

# 2. The gap list

Every MISSING and PARTIAL row, ordered by what a customer or the owner actually loses.
Ranking reason is given for each.

### Tier A — a customer is given unsafe or wrong guidance, or loses the outcome they came for

| # | ID(s) | Gap | Why it ranks here |
|---|---|---|---|
| 1 | R-7.26 | The anti-legionella veto is **English-only** (`legionella (cycle\|treatment\|flush)`). Swedish `legionellafunktionen` / `legionellaskyddet` / `legionellaprogrammet` pass the hard veto. | Swedish is the primary locale, and legionella is a **life-safety** setting the owner listed explicitly. Same welded-compound bug class as `köldmedieläckage` — which has already shipped twice here. Only the LLM classifier stands behind it, and `classify_unsafe` fails **open** on any exception. |
| 2 | R-8.15, R-10.13 | Internal control-valve work has **no** keyword pattern and **no** conformance rule. | The owner named it twice (§8 filters, §10 flag list). Opening a filtration control valve on a pressurised vessel is exactly the class the backstop exists for, and the backstop cannot see it. |
| 3 | R-8.07 | "Alter pump start or stop pressure" has no veto pattern (`stopptryck`/`starttryck` appear only in the conformance detector). | Named in §8's explicit do-not list. A draft saying "sänk stopptrycket till 4 bar" reaches the customer unless the LLM catches it. |
| 4 | R-7.20, R-7.21, R-7.22, R-7.23, R-7.24, R-7.27 | Factory settings, pump speed, compressor limits, **electric-backup limits**, sensor calibration and frost protection are prompt-text-only; none is in the keyword veto. Electric-backup limits have no detector at all. | §7's forbidden-menu list is the owner's core "only normal user menus" boundary. Prompt bodies are `get_or_create`-seeded and owner-editable, so one prompt edit silently removes six of these rules. |
| 5 | R-13.21, R-13.22 | The form button is **not shown on `decision="escalate"` or `report.service_recommended=true`** — only on an explicit ask, on `severity="service"`+solve, and after a lead is already sent. | This is the single highest-volume commercial path in the letter. Every customer who is escalated and then declines consent, or abandons contact collection, is shown no way to reach the form — the exact "the conversation ends and nothing happens" outcome §13 was written to prevent. |
| 6 | R-12.10, R-12.20 | **No address-level service-area check exists.** Only postcodes are geocoded. | §12 says the postcode check is *preliminary* and the full address gets the final check at the form. Half the mechanism is missing, so a customer at a large postcode's far edge can be told "inside area", book, and have a technician dispatched out of range. |
| 7 | R-9.10 | Nothing in code prevents a web-derived fact from setting `in_docs=true`; the restriction is a prompt sentence in the digest agent. | §9's whole point is that a marketing page must never become the basis for a repair instruction. `in_docs=true` is what unlocks a confident solve. |
| 8 | R-5.01 | The shipped 102-entry general-knowledge corpus imports with `is_approved=False`, and retrieval filters on `is_approved=True`. | §5 is the letter's centrepiece — "use general knowledge before the manual". Until the owner runs the approval pass, that layer returns **nothing** in production and every non-catalog case degrades to a handoff. The behaviour is correct by design (R-5.14); the *deployment state* is the gap. |
| 9 | R-13.27 (undercut) | `i18n.py:229` `outside_area_decline` tells the customer "jag kan inte **boka ett teknikerbesök** där", and `i18n.py:213` `terminal` says "Nordland VVS **hör av sig**" after a no-lead close. | Directly contradicts §11/§13: the bot states it books visits, and tells a customer with no lead that Nordland will be in touch. Confirmed independently — still open from the 2026-09-14 audit. |

### Tier B — the owner loses information, control or trust in the record

| # | ID(s) | Gap | Why it ranks here |
|---|---|---|---|
| 10 | R-1.12, R-4.16, R-5.07, R-13.11 | **No `symptoms` field exists.** `orchestrator.py:1228` passes `symptoms=""` to every manual-specialist render, unconditionally. | §1 lists it as a case-state field, §4 requires it preserved, §5 requires retrieval to use it, §13 requires it transferred. One missing slot breaks four requirements, and the specialist prompt has a permanently blank line. |
| 11 | R-1.15, R-1.16, R-5.10, R-5.12 | `operating_context` and `readings` are extracted, stored in JSON, and then **never used**: not rendered into a prompt, not flushed to `Session`, not in the lead, not in the prefill, not in retrieval. | The bot asks the customer for gauge readings and operating context, and throws the answers away. The customer pays the cost of answering and gets none of the benefit. |
| 12 | R-1.26 | `warranty` is declared in `EXTRA_SLOTS` and **never written by anything**. | A dead field that reads as implemented. The owner listed warranty as a case-state field; the office will never see one. |
| 13 | R-13.05 | The prefill payload's `"subtype"` key is filled from `problem_category.label` (the fault class), not the equipment subtype. | The office form is prefilled with a wrong-meaning value, and `test_prefill_endpoint_returns_technical_fields` passes because it asserts the key exists, not its meaning. Worse than missing: it looks right. |
| 14 | R-13.13, R-13.14, R-13.15 | Photos, OCR text and completed checks are not in the prefill payload. | §13 names all three as facts the chatbot must transfer. The office re-asks for work the customer already did. |
| 15 | R-12.13, R-12.16 | **No polygon edit route.** Categories can only be assigned at creation. | §12 explicitly asks for polygons that can be "drawn, edited, deleted". Correcting a boundary means deleting the area (losing its category assignments and border_km) and redrawing it. |
| 16 | R-11.10, R-11.11, R-11.12, R-11.13 | `S11-SUMMARY-STATES-GAPS` only fires when the **model** is missing. Missing error code, contact, consent and booking are never checked. | §11 names five things the summary must disclose; the detector covers one. A technician can receive a confident-sounding recap of a case with no consent captured. |
| 17 | R-9.04 | No path retrieves an official manufacturer **user manual** for an unmatched unit. | §9's source priority #2. `consult_web` is explicitly barred from repair procedures, so the second-best source in the letter simply does not exist. |
| 18 | R-8.12 | "Do not repeatedly force regeneration" has no code, no rule, and no prompt line. | Named explicitly in §8. The filtration specialist is even told to *check* regeneration status, with nothing distinguishing checking from repeatedly forcing. |
| 19 | R-10.26, R-11.15 | `AgentPrompt.inject_faq` defaults to `True` for the safety and summarizer roles. | Behaviour is correct (neither role is ever given FAQ), but the owner's dashboard says the opposite of what the letter requires. A config surface that lies is a future bug. |
| 20 | R-12.21 | Wells are not separable from water pumps (`water_pump_well` is one category). | §12 asks for four independently-configurable service areas; three exist. |

### Tier C — detectors too narrow to fire on a realistic violation

These do not change bot behaviour; they mean the eval harness reports "PASS" on conversations
that actually broke the spec. Ranked below Tier B because they cost *knowledge*, not outcomes.

| # | ID(s) | Gap |
|---|---|---|
| 21 | R-7.13, R-7.14 | `RAISE_SETTING` misses `höj framledningstemperaturen`, `öka framledningen`, `skruva upp kurvan`, and — because `öka` is bound only to `värmekurvan\|kurvan` — the plain Swedish `öka varmvattentemperaturen`. |
| 22 | R-9.16 | `REFER_AWAY` misses `kontakta NIBE`, `kontakta din installatör`, `hör av dig till serviceverkstaden`. |
| 23 | R-4.12 | `S4-BRAND-PRESERVED` checks a hard-coded 13-brand list; Nilan, Jäspi, Vaillant, Danfoss, Villavarme etc. are never checked. |
| 24 | R-8.16 | Conformance `byta\s+filtermassa` misses the imperative `byt filtermassan`. (`guardrails.py` gets this right — detector only.) |
| 25 | R-8.13 | Conformance `öka\s+doseringen` misses `höj doseringen`, `öka dosering`. |
| 26 | R-8.11 | Conformance `lyfta? (upp )?(brunns)?pumpen` requires the definite form. |
| 27 | R-2.x | `CONTACT_ASK` is three Swedish phrases (`vad heter du`, `vilket telefonnummer`, `din e-post`). "Kan du ge mig ditt namn", "Vad är ditt telefonnummer" escape it. |

### Tier D — prompt-text-only rules with no drift protection

The largest single block: **34 requirements** across §5, §6, §7, §9, §10 and §11 are enforced
only by a sentence in a seeded `AgentPrompt.body`. Because `seed_kb` uses `get_or_create`,
none of them reaches an install whose prompt row predates the rule, and any owner edit in the
dashboard can delete them without a test failing. `_CONTRACT_ADDENDA` protects exactly five
keys today (`never promise`, `no_action_needed`, `onset is unknown`, the summarizer language
rule, `consult_web`) plus the gas-safety exception. Everything else in §6's source order,
§7's setting-change discipline, §5's anti-invention list and §11's disclosure list is
unprotected.

Notable within this block, in order: **R-6.02** (the seeded specialist prompt numbers the
manual *third*, contradicting §6's "source order 1 = exact manual"), **R-5.21–R-5.26** (the
entire anti-invention list), **R-7.07–R-7.11** (explain / note original value / one small
change / evaluate), **R-11.01** (summarizer must not add technical facts).

---

# 3. Cheapest closures

### Surgical — a regex, a dict entry, or a few lines. Do these first.

| Gap | Change | Effort |
|---|---|---|
| #1 anti-legionella | Add `legionella\w*` (Swedish compounds) to `_FORBIDDEN_INSTRUCTION` alongside the existing English phrases. One alternation. | 1 line + 1 test |
| #2 control valve | Add `(öppna\|demontera\|ta isär\|skruva \w+ på) …(styrventil\w*\|ventilhuvud\w*)` and `open/dismantle the control valve` to `_FORBIDDEN_INSTRUCTION`; add a `FORBIDDEN_GUIDANCE` entry. | ~4 lines + 2 tests |
| #3 start/stop pressure | Add `start-?\|stopp?tryck\w*` / `start.{0,6}stop pressure` to `_FORBIDDEN_INSTRUCTION`. | 1 line + 1 test |
| #4 §7 forbidden menus | Add six alternations to `_FORBIDDEN_INSTRUCTION`: `fabriksinställning\w*`, `pumphastighet\w*`/`varvtal`, `kompressorbegränsning\w*`, `tillskottsvärme…begränsning`/`elpatron…begränsning`, `givarkalibrering\w*`/`kalibrera givar\w*`, `frysskydds?inställning\w*`. The conformance detector already has most of these — copy them across. | ~8 lines + 1 table test |
| #12 dead `warranty` slot | Either add `warranty` to `bulk_extract`'s field list and `_apply_extracted_facts`, or delete it from `EXTRA_SLOTS`. **Deleting is the honest cheap fix**; extracting is the spec-complete one (~6 lines either way). | 1–6 lines |
| #13 prefill `subtype` | `chat/views.py:183` → `slots.get("subtype")`, and add `problem_category` under its own key. Fix the test to assert the value, not the key. | 2 lines + 1 test |
| #14 prefill photos/OCR/checks | Add `ocr_text`, `troubleshooting_performed` and a photo-URL list to the `technical` block. OCR and checks are already on the session; photos need a signed URL per `CustomerFile`. | ~10 lines (OCR+checks); photos need a URL scheme |
| #16 summary disclosure | Broaden `_summary_gaps` to fire on missing error code / contact / consent / booking, not just model. The `_SUMMARY_DISCLOSES` regex already exists. | ~15 lines + 4 tests |
| #21–#27 narrow detectors | Widen seven regexes in `spec_conformance.py`. Each is a one-line alternation plus a "this realistic violation is now caught" test. | ~10 lines + 7 tests |
| #19 inject_faq flags | Set `inject_faq=False` in the `seed_kb` defaults for `safety`, `summarizer`, `router`, `qa`; add a test asserting it. | 2 lines + 1 test |
| 41 untested IMPLEMENTED rows | Add assertions for the highest-value ones: R-3.01 (escape chip always present), R-3.07 (subtype narrows candidates), R-3.13 (photo nudge), R-1.07 (match_confidence), R-12.22 conformance rule. | ~1 day total |
| #5 form-button triggers | `orchestrator.py:1308` → `cs["_emit_form"] = _wants_form(user_text) or cs["report"].get("service_recommended") or cs.get("severity") == "service"`; mirror it in `_unsupported_step` and the routing-rule path. **Verify the `outside_area` suppression still holds** (`form_buttons.py:37` already gates it). | ~5 lines + 3 tests |
| #9 booking language | Rewrite `outside_area_decline` and `terminal` so neither claims the bot books or that Nordland will follow up when no lead exists. Add a `terminal_no_lead` key chosen on `cs["report"]["service_recommended"]`. | ~10 lines + 2 tests |

### Real design work — do not attempt these as a patch

| Gap | Why it needs design |
|---|---|
| #6 address-level service-area check (R-12.10, R-12.20) | Needs an **address geocoder**: a provider choice (offline dataset vs. paid API), a caching and rate-limit story, a failure policy (what status does an ungeocodable address get?), a new dashboard test box, and a decision about where the check runs — at prefill fetch, at form submit, or both. Also a PII question: sending full customer addresses to a third-party geocoder. |
| #7 web-source `in_docs` enforcement (R-9.10) | Needs provenance tracking through the digest: the orchestrator must know *which* facts in the answer came from `consult_web` to refuse `in_docs=true`. Today `_maybe_consult` folds the digest into a re-render and the origin is lost. Either tag consult-derived content and force-cap confidence when a `[W…]` tag appears in `troubleshooting_performed`, or split the decision into `in_docs` vs `in_web`. |
| #8 corpus approval (R-5.01) | Policy, not code. The owner must review 102 entries. `tools/eval/approve_corpus.py` exists but bulk-approving defeats the §5 "only approved or verified" rule. Needs an owner decision on a review workflow and a dashboard queue. |
| #10/#11 symptoms, operating_context, readings (R-1.12, R-1.15, R-1.16) | Cheap to *plumb* individually, but doing it right means deciding the case-state→Session→lead→prefill contract once: which of the 29 §1 fields get typed columns, which stay JSON, and what the lead payload owes the office. Doing it field-by-field is how the current inconsistency arose. |
| #15 polygon edit (R-12.13) | Needs an edit route, a Leaflet.draw edit mode wired to an existing shape, an optimistic-concurrency story (two staff editing one area), and a decision on whether edits are versioned — a boundary change silently reclassifies existing customers. |
| #17 official manual retrieval (R-9.04) | A genuinely new capability: finding, fetching, validating and caching an official PDF manual for an arbitrary brand/model, then deciding whether it is trustworthy enough to set `in_docs=true`. This is the single largest unbuilt item in the letter. |
| Tier D (34 prompt-only rules) | The mechanism exists (`_CONTRACT_ADDENDA`) and works. The design question is *which* rules deserve code ownership — every rule added to the addendum grows every prompt and costs tokens on every call. Needs a policy: safety-class and contract-class rules are code-owned; tone and style stay in the body. Then a test asserting every safety-class rule is in the addendum. |

---

# 4. Ambiguities for the owner, not the engineer

1. **§5 vs §6 source ordering directly conflict.** §5 says search approved general knowledge
   *first* and load the manual only when the answer is model-specific. §6 says the standard
   specialist's source order is manual → internal knowledge → general FAQ. The seeded prompt
   splits the difference (brand notes 1, general knowledge 2, manual 3) with a grounding rule
   layered on top. An engineer cannot pick; the owner must say which wins when a manual and an
   approved general entry give different safe advice for the same symptom.
2. **"approved" vs "verified" (§5).** The letter lists both as separate states and the metadata
   list names "verification status". The code has one boolean, `is_approved`. Are these two
   states with different trust levels (e.g. "verified" may ground a confident solve, "approved"
   may only suggest a check), or synonyms?
3. **Are wells a separate service area from water pumps (§12)?** The letter names four
   categories for independent polygons (heat pumps, water pumps, water wells, water filters);
   the taxonomy has three (`water_pump_well` is one). Splitting it touches categories, chips,
   general-specialist roles, form buttons and every polygon assignment — worth doing only if
   the coverage genuinely differs.
4. **What does "the button should be shown" mean on a refused escalation?** §13 lists four
   triggers including `decision="escalate"`. If a customer escalates and then *declines*
   sending their details, should the form button still appear? Showing it respects §13
   literally; suppressing it respects the customer's "not yet". Currently neither is
   implemented — the button simply never appears.
5. **Which "previous installation" facts justify the out-of-area override (§12)?** The letter
   names three companies. The code matches a free-text installer name by case-insensitive
   substring in *either* direction, so a customer typing "Nordborr" matches, but so would
   "nord". Should the override require evidence (an invoice, a serial in the CRM), or is the
   customer's word sufficient?
6. **May the bot ever state a component location from general knowledge (§5)?** The §5
   anti-invention list forbids inventing "a component location", but §10 explicitly allows
   "checking external normal controls" and the general specialists must tell a customer where
   to look at a gauge. The boundary between "where the manometer generally is" and "a
   model-specific component location" is not drawable from the text.
7. **§13's "prefilling the existing form" vs "embedding the form in the chatbot."** The letter
   lists six options and asks for a recommendation. The signed-token prefill shipped. If the
   owner would rather embed, that changes §13's entire surface — confirm before further work.
