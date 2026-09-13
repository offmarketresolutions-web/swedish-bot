# Nordland VVS — owner workflow specification (source of truth)

Verbatim letter from the Nordland VVS owner describing the intended chatbot workflow,
recovered from the original conversation and stored here so it cannot be lost again.
`tools/eval/spec_conformance.py` checks real conversation transcripts against the
machine-checkable rules in this document.

---

Hi Bobby, Sorry for the long message. I want to describe the intended workflow clearly and separate the changes by agent and system component, so we can avoid misunderstandings and duplicated work. The main service scope for Nordland VVS is:

* heat pumps from most manufacturers,
* water pumps,
* water wells and domestic-water systems,
* pressure tanks and pump-control systems,
* water filters,
* and water-treatment systems.

The chatbot should first use verified general Nordland VVS knowledge for common system-level problems. It should move to an exact model manual only when the answer depends on model-specific information. If no safe verified customer-level action is available, or if the equipment previously worked normally and has suddenly changed without a clear user-setting explanation, the customer should be offered Nordland VVS service. Below I have divided the requested changes by agent and system area.

1. SHARED CASE STATE / BACKEND

Please create or update a shared case object that follows the customer through the complete pipeline. It should preserve, when available:

* main category,
* equipment subtype,
* manufacturer,
* customer-entered model text,
* confirmed catalog model,
* catalog machine ID,
* catalog-match confidence,
* serial number,
* alarm code,
* alarm text,
* problem description,
* symptoms,
* when the problem started,
* whether it appeared suddenly or has always existed,
* operating context,
* pressure and temperature readings,
* previous checks,
* results of previous checks,
* uploaded photos,
* OCR results,
* postcode,
* service-area status,
* matched service-area polygon,
* installer or seller,
* previous Nordland installation status,
* warranty information,
* recommended form type,
* form-submission status,
* and booking status.

Each customer message should be analysed for all useful facts, not only the value of the currently active question. Example: “It is an IVT Geo 600 and it shows ‘För stor skillnad framledning. HP’ when it makes hot water.” should preserve:

* category: heat_pump,
* subtype: liquid_to_water,
* brand: IVT,
* entered model: Geo 600,
* alarm text: För stor skillnad framledning,
* alarm family/code: HP,
* operating context: domestic hot-water production.

The customer must not be asked for those facts again later.

2. INTAKE AGENT

Purpose:

* identify the main category,
* ask for the installation postcode early,
* identify the equipment sufficiently for routing,
* collect only missing facts,
* and avoid technical troubleshooting.

Required behaviour:

1. Read the complete customer message before asking a question.
2. Extract all useful facts from the message.
3. Never ask for information already present in:
   * previous messages,
   * known facts,
   * uploaded images,
   * OCR,
   * or structured case data.
4. Ask one clear logical question at a time.
5. Do not force the customer through a fixed questionnaire when sufficient information is already available.
6. Treat an irrelevant answer such as “bb” as off-target.
7. Re-ask the missing question once.
8. After two failed attempts, record the value as unknown and continue only when possible.
9. Do not ask for name, telephone number, email address, or full address during technical intake.
10. Ask for postcode early, directly after the main category is known.

Suggested postcode wording: “Vilket postnummer finns anläggningen på? Jag behöver det för att kontrollera om adressen ligger inom vårt arbetsområde.” The postcode should:

* accept Swedish postcodes with or without a space,
* be normalized to five digits,
* and be validated before service-area checking.

3. MODEL SELECTION AND CATALOG MATCHING

This is mainly backend and UI logic. Do not show a short or incomplete model list as if it were the complete manufacturer catalog. For the model step, the customer should be able to:

* enter the exact model as free text,
* search the full catalog for the selected manufacturer,
* upload a nameplate photo,
* select “Jag vet inte”,
* or select “Annan modell”.

When equipment subtype is known, suggestions may be filtered by subtype. Example:

* ground-source heat pumps should show relevant liquid-to-water models,
* air-to-water should show relevant air-to-water models,
* exhaust-air should show relevant exhaust-air models,
* air-to-air should show relevant air-to-air models.

A partial model name must not automatically be converted into one exact catalog machine. Example: “Geo 600” may refer to Geo 600C or Geo 600E. When several matches are possible:

* preserve the customer-entered model text,
* do not automatically select the first match,
* keep catalog_machine_id=null,
* keep supported=false until clarified,
* ask for the exact suffix,
* or request a nameplate photo.

Only assign supported=true after an exact or clearly verified model match.

4. ROUTER AGENT

Purpose:

* classify the category,
* preserve the real manufacturer,
* determine whether an exact local catalog match exists,
* classify the main problem,
* and assess severity.

The Router should not troubleshoot or search manuals. Supported categories:

* heat_pump
* water_pump_well
* water_filtration
* unknown

Important meaning: supported=true means that an exact verified machine exists in the local catalog and the correct local manual or machine knowledge can be attached. supported=false means only that no exact verified local catalog match exists. supported=false must not mean that Nordland VVS does not service the equipment. Preserve known manufacturers even when they are not in the local catalog. Examples:

* NIBE remains NIBE,
* CTC remains CTC,
* Thermia remains Thermia,
* Grundfos remains Grundfos when it is the main water pump,
* Callidus remains Callidus when it is the complete filter manufacturer.

Do not replace known non-catalog brands with “other”. When supported=false:

* preserve manufacturer,
* preserve model text,
* preserve equipment subtype,
* preserve all symptoms and alarms,
* and route the case to the Intelligent Specialist.

5. GENERAL KNOWLEDGE RETRIEVAL BEFORE MANUAL LEVEL

Please add a retrieval step against the approved general Nordland VVS knowledge base before requiring an exact machine manual. Many customer problems are system-level and not manufacturer-specific. Examples include: Heat pumps:

* no heat,
* no hot water,
* low or high visible system pressure,
* large temperature difference between supply and return,
* suspected poor flow,
* circulation symptom

s,

* unusual noise,
* sudden performance loss,
* icing and defrost symptoms,
* poor airflow,
* air-filter problems.

Water pumps and wells:

* no water,
* low or fluctuating pressure,
* pump not starting,
* pump running continuously,
* frequent starting and stopping,
* pressure dropping without water use,
* air in the water,
* visible leakage,
* possible freezing,
* abnormal sound.

Water filters:

* poor water quality,
* iron or manganese staining,
* smell or taste,
* discoloured water,
* hardness,
* low pH,
* filter not regenerating,
* backwash problems,
* low pressure after the filter,
* salt-related problems,
* visible leakage.

The retrieval should use:

* category,
* subtype,
* symptoms,
* problem description,
* onset,
* operating context,
* alarm text,
* pressure or temperature observations,
* and checks already completed.

Only entries marked approved or verified should be used. Suggested metadata for knowledge entries:

* category,
* equipment subtype,
* manufacturer_specific,
* applicable manufacturers,
* symptoms,
* operating context,
* onset type,
* safe customer checks,
* exclusions,
* service-required actions,
* source type,
* verification status,
* reviewed date,
* internal source ID.

Preferred order:

1. Search approved general Nordland VVS knowledge.
2. Give one relevant safe customer-level check when the knowledge sufficiently supports it.
3. Ask for the result when it affects the next step.
4. Load the exact machine manual when the answer depends on model-specific information.
5. If neither source supports a safe action, offer Nordland VVS service.

General knowledge must not be used to invent:

* an exact alarm-code meaning,
* a menu path,
* a reset sequence,
* a component location,
* exact technical limits,
* or a model-specific maintenance procedure.

6. STANDARD SPECIALIST AGENT

This agent is used when an exact verified local catalog machine and appropriate documentation are available. Source order:

1. Exact manufacturer manual for the identified machine
2. Approved Nordland VVS internal knowledge
3. Approved general FAQ or troubleshooting knowledge

The exact manual should control:

* alarm-code meaning,
* menu paths,
* reset procedures,
* normal user settings,
* model-specific maintenance,
* component locations,
* and exact limits.

The agent should:

* give one safe relevant check at a time,
* avoid long speculative lists,
* avoid repeating checks already completed,
* stop when the safe customer-level checks are exhausted,
* and offer Nordland VVS service when professional work is needed.

The agent must cover:

* heat pumps,
* water pumps,
* water wells,
* pressure systems,
* water filters,
* and water-treatment systems.

7. CUSTOMER COMFORT AND NORMAL USER SETTINGS

This belongs mainly in the Standard Specialist and Intelligent Specialist logic. The chatbot should be able to help customers with normal user-accessible settings when an exact manual or approved Nordland VVS knowledge supports the action. Heat-pump examples:

* increasing or decreasing normal indoor-temperature settings,
* making a small documented customer-level heating adjustment,
* adjusting normal heating-curve offset when the manual treats it as a user setting,
* selecting economy, normal, or comfort hot-water mode,
* activating temporary extra hot water,
* adjusting normal heating or cooling mode,
* checking ordinary schedules,
* checking holiday mode,
* checking economy or night reduction,
* adjusting normal air-to-air fan and temperature settings.

The system must distinguish between:

1. A condition that has always existed or has developed gradually.
2. A sudden change after the system previously worked normally.

If the customer says:

* the house has always been slightly too cold or warm,
* hot-water comfort has always been insufficient,
* or the normal comfort level has never been correct,

then a documented normal customer setting may be appropriate. The chatbot should:

* explain what the setting affects,
* note or ask the customer to note the original value,
* recommend only a small change,
* change one setting at a time,
* and allow time to evaluate the result.

If the customer says the system previously worked normally but has suddenly become too cold, too warm, or produces less hot water:

* do not assume the ordinary setting is the cause,
* do not simply increase the heating curve,
* do not simply increase the hot-water setting,
* first check alarms, operating mode, schedules, holiday mode, power interruption, system pressure, circulation, electric backup, or another verified operational issue,
* and offer Nordland VVS service when no clear customer-setting change explains the problem.

Only normal user menus are allowed. Do not guide the customer into:

* installer menus,
* service menus,
* factory settings,
* pump-speed settings,
* compressor limits,
* electric-backup limits,
* sensor calibration,
* safety settings,
* anti-legionella settings,
* or frost-protection settings.

8. SUDDEN FAULT RULE FOR ALL SERVICE CATEGORIES

This principle should apply to all technical customer-facing specialists. If equipment previously worked normally and suddenly develops a fault, treat it as a possible technical problem rather than only a setting issue. Heat pumps: Examples of sudden changes:

* loss of heating,
* reduced hot water,
* loss of cooling,
* new alarm,
* unusual noise,
* sudden pressure change,
* sudden icing,
* or sudden loss of normal operation.

After limited safe checks, offer Nordland VVS service when no clear user-setting explanation exists. Water pumps and wells: Examples of sudden changes:

* no water,
* significantly lower pressure,
* fluctuating pressure,
* frequent pump starts,
* pump runs continuously,
* pump no longer starts,
* air suddenly appearing in the water,
* new leakage,
* new alarm,
* or abnormal noise.

Do not attempt to compensate by changing pressure settings. Do not instruct the customer to:

* adjust a pressure switch,
* alter pump start or stop pressure,
* adjust pressure-tank precharge,
* bypass pump protection,
* open a pump controller,
* or lift a well pump.

After relevant safe observations, offer Nordland VVS service. Water filters: Examples of sudden changes:

* sudden iron or manganese staining,
* sudden smell or taste,
* sudden discolouration,
* sudden hardness,
* filter no longer regenerating,
* backwash no longer working,
* sudden low pressure after the filter,
* new alarm,
* or new leakage.

Do not attempt to solve the fault by:

* repeatedly forcing regeneration,
* increasing chemical dosing,
* changing installer programming,
* opening the control valve,
* or changing internal filter media.

After relevant safe checks, offer Nordland VVS service. General rule: If the system previously worked normally and the change is sudden and unexplained:

* do not make large setting changes,
* do not continue into professional troubleshooting,
* and offer Nordland VVS service.

9. INTELLIGENT SPECIALIST FOR UNMATCHED EQUIPMENT

This agent is used when no exact local catalog machine or local manual is available. It should still handle:

* heat pumps from most manufacturers,
* water pumps,
* water wells,
* domestic-water systems,
* water filters,
* and water-treatment systems.

Source priority:

1. Approved Nordland VVS general knowledge
2. Exact official manufacturer user manual
3. Exact official manufacturer product page or technical datasheet
4. Official manufacturer support information

For non-IVT products, web research should be limited to:

* official manufacturer websites,
* official national manufacturer websites,
* or official importers/distributors publishing original manufacturer information.

Do not use:

* forums,
* social-media posts,
* YouTube videos,
* repair blogs,
* retailer articles,
* anonymous manuals,
* or uncertain copied documents

as the basis for technical customer advice. An official product page may be used for:

* product identification,
* intended use,
* basic specifications,
* controller type,
* and normal customer controls.

A marketing product page must not be used as the sole basis for repair instructions. Only simple customer-level checks may be provided. If no verified safe action is available, or if the safe checks do not solve the issue, offer Nordland VVS service. Do not refer the customer elsewhere solely because:

* the equipment is not IVT,
* the manufacturer is not in the local catalog,
* the manual is missing locally,
* or Nordland VVS did not originally install it.

10. SAFETY CLASSIFIER

The Safety Classifier should remain a final safety backstop. It should cover instructions concerning:

* heat pumps,
* water pumps,
* water wells,
* pressure systems,
* water filters,
* and water-treatment equipment.

It should flag instructions involving:

* internal electrical work,
* refrigerant work,
* expansion vessels,
* safety valves,
* pressure-tank precharge,
* pressure-switch adjustment,
* pulling a well pump,
* opening pump controllers,
* opening pressurized filter tanks,
* changing filter media in pressure vessels,
* internal control-valve work,
* chemical dosing changes,
* bypassing safety devices,
* installer/service menus,
* or other professional tasks.

It should allow safe observations and routine owner maintenance when clearly supported, such as:

* reading a display or gauge,
* checking visible leakage,
* checking external normal controls,
* cleaning user-accessible air filters,
* checking salt level,
* adding approved salt,
* checking normal regeneration status,
* and following a verified user-serviceable filter procedure.

Inject FAQ should remain disabled for the Safety Classifier.

11. SESSION SUMMARIZER

The summarizer should not troubleshoot or add technical facts. It should summarize:

1. Equipment identification
2. Problem and symptoms
3. Severity and reason
4. Safe checks completed or suggested
5. Results
6. Recommended next action
7. Contact, consent, form, and booking status

It must state when important details are missing, for example:

* exact model not captured,
* no error code captured,
* contact details not captured,
* consent not captured,
* booking not confirmed.

It must not treat a shown form button as a submitted service request. Inject FAQ should remain disabled for the Session Summarizer.

12. POSTCODE AND SERVICE-AREA CONTROL

The postcode should be requested early, after the main category is known. The intended service area is approximately:

* the coastal corridor from Örnsköldsvik to Uppsala,
* approximately 50 kilometres inland,
* with separate extensions toward southern Sollefteå,
* and toward Ånge.

I would like the service area to be controlled through editable geographic polygons. Suggested process:

1. Normalize the Swedish postcode.
2. Geocode the postcode to coordinates.
3. Test the coordinate against the configured polygons.
4. Return:
   * inside_area
   * border_review
   * outside_area

The polygon should be the main source of truth. Because postcode areas may be geographically large, postcode checking should be preliminary. The full installation address should receive the final check when the customer opens or submits the website form. Border cases should be allowed to submit a service request for manual review. The administration interface should preferably allow polygons to be:

* drawn,
* edited,
* deleted,
* activated or deactivated,
* assigned to one or more service categories,
* imported/exported as GeoJSON,
* and tested against a postcode or full address.

It should be possible to have different service areas for:

* heat pumps,
* water pumps,
* water wells,
* and water filters.

Previous installations sold or installed by:

* Nordland VVS,
* Bylunds VVS,
* Nordborr i Sundsvall

should be accepted for Nordland VVS review even when outside the normal polygon. The previous-installation override should be checked before finally rejecting an outside-area case.

13. WEBSITE FORM INTEGRATION

I would like the chatbot to connect to the existing forms on the Nordland VVS website. Please check which form plugin or form system the website currently uses and recommend the best solution. Possible approaches include:

* prefilling the existing form,
* a REST API,
* a webhook,
* a server-side temporary case record,
* a secure case token,
* or embedding the form in the chatbot.

The preferred solution should avoid putting sensitive customer information in public URL parameters. The chatbot should transfer the technical facts already collected:

* category,
* subtype,
* brand,
* model,
* alarm code,
* alarm text,
* problem description,
* symptoms,
* postcode,
* photos,
* OCR,
* and checks already completed.

The customer should then add:

* name,
* telephone number,
* email address,
* and full installation address.

Please add backend-controlled action buttons:

* heat_pump → heat-pump service form
* water_pump_well → water-pump and water-well service form
* water_filtration → water-filter service form
* quote_request → quotation form

The form button should be shown when:

* decision="escalate",
* report.service_recommended=true,
* severity="service",
* or the customer directly asks

to book service or request a quotation. The AI should not invent URLs. Form URLs should be configured in the backend. Showing the button does not mean the form is submitted or that a booking is confirmed.

14. RESPONSIBILITY AND NEXT STEP

I will continue reviewing and adding:

* Nordland VVS technical knowledge,
* general troubleshooting guides,
* manufacturer manuals,
* machine-specific notes,
* and verified knowledge-base content.

Please review the full workflow and implement the most appropriate technical solution for:

* shared persistent case state,
* multi-fact extraction,
* model matching and ambiguity handling,
* off-target answers,
* routing,
* general-knowledge retrieval before manual retrieval,
* model-selection UI,
* service-area checking,
* postcode handling,
* website-form integration,
* form buttons,
* and data prefill.

Please also adjust prompts, output schemas, or workflow components wherever the application architecture requires it. Let me know when a schema or contract needs to change so the agent outputs and backend remain aligned. /ponytail /ponytail-review /ponytail-audit /karpathy-guidelines /anthropic-skills:swarm-orchestrator use sonnet and opus for coding and fable as the orcheestrator /gsd-plan-phase /web-atelier:execute-phase /web-atelier:ui-review /grill /grill-me /grill-with-docs

```

/


```