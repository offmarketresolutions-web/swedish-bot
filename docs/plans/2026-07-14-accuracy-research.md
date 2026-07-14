# Accuracy research — how to materially raise answer accuracy (2026-07-14)

Ground truth read: `docs/evals/2026-07-14-v2-validation.md`, `docs/evals/2026-07-13-gap-analysis.md`,
`chat/orchestrator.py`, `chat/context.py`, `kb/semantic.py`, `tools/eval/judge.py`.

## Architecture as it stands (no change needed to re-derive this)

- Deterministic FSM (`chat/orchestrator.py`, `_intake_step` → `_specialist_step` → escalate),
  not an agentic retrieval loop.
- Per-machine **full-manual caching**: `chat/context.py::machine_pdf_context` puts the whole PDF
  in a Gemini context cache (or inlines if under the token floor) — there is no manual-chunking
  step today, and correctly so at this corpus size (see do-NOT-do list).
- `kb/semantic.py` is a bolt-on augmentation: in-memory cosine over a corpus of "dozens of rows"
  (FAQ/guides/machines), gemini-embedding-2, `RETRIEVAL_DOCUMENT`/`RETRIEVAL_QUERY` task types
  already correctly split (line 67 vs 87/163/192) — this part already matches best practice.
- Confidence gates: `SEMANTIC_MATCH_CONFIDENCE = 0.65` (deliberately capped below the specialist's
  `CONFIDENCE_GATE=0.70`, per the comment at `kb/semantic.py:33-38` — a documented, reasoned choice,
  not a bug), plus an `in_docs` cap in `_specialist_step`.
- Judge (`tools/eval/judge.py`): deterministic hard checks (DIY leak via read-only import of
  `guardrails._FORBIDDEN`, outcome-match, PII echo, lead completeness) + LLM-judge (Gemini Flash,
  temp 0, per-category rubric dims) for soft dimensions (C-REMEDY, C-SCOPE, C-TONE, etc.).

## Known failure modes (from the two ground-truth docs, not re-derived)

1. No terminal "confirmed resolved" state in the FSM — every post-`solve` turn re-enters the
   specialist with no dedicated confirmation type, so `in_docs` naturally comes back false and the
   hard-cap forces escalation. Root cause is FSM state design, not retrieval.
2. General-mode escalation is high because the 102-entry FAQ/knowledge corpus is unapproved —
   `rank_general_knowledge`/`rank_guides` correctly return nothing for an unapproved corpus, so this
   is a data-approval gap, not a retrieval-algorithm gap.
3. Imprecise generic checks for the wrong technology (exhaust-filter advice suggested for a
   ground-source unit) — happens in **general mode**, where there is no bound machine and hence no
   manual in context at all; the model is drafting from world knowledge, not the manual.
4. Judge noise — Flash at temp 0 is the same rubric-scoring model quota-shared with production, no
   documented human-calibration pass yet.
5. Electrical-panel DIY leak past both guardrail layers (gap-analysis #3) — a keyword/prompt gap in
   `chat/guardrails.py`, not a retrieval-accuracy issue, but it interacts with #3 above: general-mode
   drafting from world knowledge is what invents unsafe generic instructions in the first place.

---

## Theme 1 — RAG accuracy for domain support bots

### Chunking (manuals with tables/error-code lookups)
Evidence: document-aware/structure-aware chunking that respects headings, sections, and — critically
— keeps tables as atomic units, outperforms fixed-size/sliding-window chunking on structured technical
documents; fixed-size chunking fragments multi-page tables and step procedures across chunk
boundaries. [Atlan — Chunking Strategies for RAG](https://atlan.com/know/chunking-strategies-rag/),
[Redis — Best Chunking Strategies for RAG Pipelines](https://redis.io/blog/chunking-strategy-rag-pipelines/),
[arXiv 2605.00318 — Structure-Aware Chunking for Tabular Data in RAG](https://arxiv.org/pdf/2605.00318).

**Applies here:** it doesn't, yet. This codebase does not chunk manuals at all — `machine_pdf_context`
puts the entire PDF in a Gemini context cache per bound machine (`chat/context.py:107-142`). The
manual's error-code tables are therefore already served whole, in original layout, to the model —
which is *better* than chunking for accuracy on a corpus this small, because chunking only exists to
solve a token-budget problem this codebase doesn't have per-machine. Chunking would be a net
regression here (risk of splitting the error-code table this bot is graded on, per gap #3-style
failures). **Do NOT chunk manuals while they fit in the cache.**

### Hybrid retrieval / rerank
Evidence: hybrid (BM25 + dense) beats either alone on real-world corpora at scale, but "use BM25 for
small keyword-heavy datasets" and pure dense retrieval "performs strongly on smaller semantic
datasets" are both cited as adequate for small corpora — the reranker step earns its cost mainly once
recall@k starts missing on datasets in the thousands-of-chunks range.
[Veer Khot — BM25 vs Dense vs Hybrid](https://veerkhot.com/articles/bm25_vs_dense_vs_hybrid_retrieval.html),
[Digital Applied — Hybrid Search Reference 2026](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026).

**Applies here:** the FAQ/guide corpus is "dozens of rows" per `kb/semantic.py`'s own docstring —
several orders of magnitude below where hybrid+reranker pays for itself. `kb/semantic.py` already has
a trigram-first / embedding-fallback design for machine identification (correct shape). The real gap
isn't retrieval algorithm sophistication — it's corpus *coverage* (item 2 below) and metadata
filtering, which is already implemented (`category_ids`, `applicable_subtypes`, `onset`, `manufacturer`
in `rank_general_knowledge`). **Do NOT add BM25/reranker infrastructure at this corpus size** — it adds
an index-management burden with no measurable accuracy delta until the corpus is 100x larger.

### Embedding model/task_type/dimension settings
`kb/semantic.py` already does `RETRIEVAL_DOCUMENT` for corpus, `RETRIEVAL_QUERY` for queries — this is
exactly the documented best practice for gemini-embedding-2/001.
[Google AI — Embeddings task types](https://ai.google.dev/gemini-api/docs/embeddings),
[technicalwriting.dev — Understanding task types](https://technicalwriting.dev/embeddings/tasks/index.html).
No `output_dimensionality` truncation is used anywhere (full 3072-dim, implicitly) — Matryoshka
truncation to 768/1536 trades a "moderate" accuracy hit for lower storage/latency
([MindStudio — Matryoshka in Gemini Embedding 2](https://www.mindstudio.ai/blog/matryoshka-representation-learning-gemini-embedding-2)).
**Applies here:** truncation is a cost/latency optimization, not an accuracy lever, and this corpus is
tiny (in-memory cosine, cached) — storage/latency aren't the bottleneck. **Do NOT truncate dimensions**
— there is no accuracy upside, only downside, at this scale.

### Metadata filtering vs pure vector
Already implemented and correctly ordered (filter first: category/subtype/onset/manufacturer, *then*
rank by cosine or keyword-overlap) — this is the standard, correct pattern and needs no change.

---

## Theme 2 — Grounding + hallucination control

### Citation-forced generation / answerability
Best practice: force the model to identify whether the retrieved context actually answers the
question before generating, and calibrate abstention thresholds rather than using a single fixed
score. Current work frames this as two separable axes — answer correctness and question answerability
— and shows mainstream models still fail to abstain well on unanswerable questions without explicit
training/prompting for it.
[arXiv 2607.08456 — Two Axes of LLM Abstention](https://arxiv.org/html/2607.08456),
[AbstentionBench discussion, arXiv 2512.19920](https://arxiv.org/html/2512.19920v1).

**Applies here:** the codebase's `in_docs` flag (referenced in gap-analysis #1 root cause and
`kb/semantic.py:36`) is exactly this idea — a binary "did the manual actually say this" signal — but
it is used only as a hard-cap gate on confidence, not as a structured field the specialist prompt must
justify per-answer. **Ranked rec:** require the specialist LLM to emit which manual passage (page/
section, or "not in manual") backed each claim in its JSON output, and log a mismatch (claims a
remedy but cites nothing) as a scoring signal in the eval judge — this converts an implicit binary
flag into an auditable, gradeable citation, cheaply (same call, added output field). **Impact: high
(closes gap #3's precise failure mode — imprecise generic advice masquerading as grounded). Effort: S.**

### Fixed 0.70 gate vs calibrated abstention
The literature's dominant recommendation is not "tune the single threshold" but "calibrate against a
labeled set and report agreement (e.g. via Beta-distributed risk preference or held-out accuracy
curves)" rather than picking one static cutoff by feel.
[arXiv 2512.19920 — Behaviorally Calibrated RL](https://arxiv.org/html/2512.19920v1).
**Applies here:** 0.70 appears to be a hand-picked constant (`CONFIDENCE_GATE` in
`core/constants.py`, referenced gap-analysis line 43) with no evidence it was derived from a labeled
set. **Ranked rec:** once the FAQ corpus is approved (unblocking real general-mode traffic), run a
threshold sweep against the golden eval set (below) and pick 0.70 vs alternatives by measured
escalation/false-resolution tradeoff — not by feel. **Impact: medium. Effort: S** (once golden set +
approved corpus exist — depends on Theme 3 and the do-NOT-yet-fix items).

### Self-consistency / verification passes
Cost-benefit at Flash pricing: a second verification call approximately doubles per-answer LLM cost.
Given the bot's current problem is *architectural* (no confirm-state, unapproved corpus) rather than
*generation noise*, a verification pass would not move the needle on the top gaps and is pure added
cost. **Do NOT add a self-consistency/verification pass** until gaps #1–#3 are fixed and the residual
error rate is actually generation-noise-shaped rather than FSM/data-shaped.

---

## Theme 3 — Eval-driven improvement loop

Best practice: build a golden set from real (not synthetic) transcripts, calibrate the LLM judge
against human labels (target κ ≥ 0.60, 75–90% raw agreement), and gate regressions on that fixed set
before each change ships.
[Galileo — Calibrate Your LLM Judge](https://galileo.ai/blog/calibrate-llm-judge-human-annotations),
[Kinde — LLM-as-a-Judge Done Right](https://www.kinde.com/learn/ai-for-software-engineering/best-practice/llm-as-a-judge-done-right-calibrating-guarding-debiasing-your-evaluators/).

**Applies here:** `tools/eval/judge.py` has zero human-calibration step today — the LLM judge's rubric
scores (C-REMEDY, C-SCOPE, etc.) have never been checked against a human rater, only the deterministic
checks (DIY leak, outcome-match) are code-verifiable and therefore already trustworthy. The 200+40
eval specs (`tools/eval/personas.py`) are synthetic personas, not mined from real transcripts — there
are no real transcripts yet (pre-launch). **Ranked rec:** (a) hand-label ~20-30 judged transcripts
across categories yourself (owner, 30-60 min) and compute raw agreement with the LLM judge's scores per
dimension — cheap, catches judge-noise before trusting it as a regression gate; (b) once live traffic
exists, mine real transcripts into the golden set rather than relying solely on synthetic personas
(the v2-validation doc's own finding — synthetic sim couldn't play a "yes it worked" arc until
manually patched — is exactly the failure mode real transcripts avoid). **Impact: high (protects every
future accuracy claim from judge noise). Effort: S for (a), M for (b).**

---

## Theme 4 — Swedish/multilingual specifics

Evidence: native multilingual embedding training outperforms "translate-then-embed" for retrieval;
Scandinavian-benchmark work shows Swedish (low-resource relative to English) still underperforms
high-resource languages on embedding quality, and embedding quality itself matters more than language
closeness.
[arXiv 2406.02396 — Scandinavian Embedding Benchmarks](https://arxiv.org/html/2406.02396v1),
[ZeroEntropy — Best Multilingual Embedding 2026](https://zeroentropy.dev/articles/best-multilingual-embedding/).

**Applies here:** `kb/semantic.py` already embeds Swedish text raw (no translation step visible in
`rank_guides`/`rank_general_knowledge`/`semantic_identify`) using gemini-embedding-2, which is
consistent with the "don't translate first" finding. No action needed on the embedding side. The
actual Swedish-language risk is elsewhere: the specialist's generation quality in Swedish (not
retrieval) is unmeasured — the eval corpus is 37 en / 17 sv (gap-analysis header), a 2:1 skew. **Ranked
rec:** weight the eval persona set closer to expected real-traffic language mix (if Nordland VVS's
actual customers are majority-Swedish, the eval is currently under-testing the majority-language path).
**Impact: medium. Effort: S** (persona-mix rebalance, no code change).

---

## Theme 5 — Structured error-code triples vs prose FAQ

Evidence: structured (error-code → cause → action) triples give explainability/traceability and are
the standard approach for industrial fault diagnosis at scale; but this benefit is largest when the
corpus is entity-dense and multi-hop (root-cause chains across components) — "most corpora are not
uniformly relational; procedural documentation and FAQs tend not to be."
[Atlan — Knowledge Graph vs RAG 2026](https://atlan.com/know/knowledge-graphs-vs-rag-for-ai/),
[DevRev — Knowledge Graphs vs RAG](https://devrev.ai/blog/knowledge-graphs-vs-rag-enterprise-ai).

**Applies here:** the manuals already contain literal error-code tables served whole to the model
(Theme 1) — the model reads the actual table, it doesn't need a separately-maintained triple store
duplicating the same facts with a staleness risk. FAQEntry already carries structured fields
(`applicable_subtypes`, `onset_type`, `safe_customer_checks`, `service_trigger` — visible in
`chat/context.py:85-87`) which *is* the lightweight structured layer this bot needs — a triple/graph
would be a second source of truth to keep in sync with the manuals for no measured benefit. **Do NOT
build a knowledge graph or a separate error-code triple store** — it duplicates data already present
in the cached PDF and the FAQEntry schema, adding a sync-drift risk (stale triples silently outrank a
manual update) for a corpus size where full-manual-in-context already gives the ground truth verbatim.

---

## Do-NOT-do list (explicit)

1. **Do not chunk the manuals.** They already fit in the Gemini context cache whole; chunking only
   trades a real accuracy risk (splitting an error-code table) for a token-budget problem this bot
   doesn't have.
2. **Do not add BM25 + cross-encoder reranker infra.** The corpus is "dozens of rows" — hybrid/rerank
   earns its complexity in the thousands-of-chunks range, not here.
3. **Do not truncate embedding dimensions (Matryoshka/output_dimensionality).** It trades accuracy for
   storage/latency this in-memory-cosine-over-dozens-of-rows system doesn't need to save.
4. **Do not add a self-consistency/second-verification LLM pass.** The current gaps are FSM-state and
   data-approval shaped, not generation-noise shaped; a verification pass doubles cost for a problem
   it doesn't address.
5. **Do not build a knowledge graph / separate error-code triple store.** The manual (served whole)
   and FAQEntry's existing structured fields already are the structured layer; a graph duplicates that
   with a sync-drift risk.
6. **Do not translate Swedish queries/documents to English before embedding.** Native multilingual
   embedding already outperforms translate-then-embed, and the codebase already does this correctly —
   don't "fix" a thing that isn't broken.
7. **Do not re-tune the 0.70 confidence gate by feel a second time.** Any change to it should be a
   threshold sweep against a calibrated golden set (Theme 3), not another single-shot guess.

---

## Top-5 ranked action plan (for a build agent)

1. **[S, high impact] Approve the FAQ/knowledge corpus (owner dashboard action) and re-run the v2 eval
   set.** This is the single highest-leverage lever available today: `rank_general_knowledge` and
   `rank_guides` are correctly implemented but retrieving against an empty (unapproved) corpus per the
   v2-validation doc's own honest-gaps section. Every "imprecise generic check" failure mode (gap-
   analysis U002) is explicitly expected to improve once approved. No code change — a data-ops task.
2. **[S, high impact] Add a per-claim citation field to the specialist LLM's JSON output** (which
   manual section/page backed each stated remedy, or "not in manual") and log citation-mismatches as a
   judge signal. Converts the existing implicit `in_docs` boolean into an auditable per-claim ground-
   truth check, directly targeting the "imprecise but not fabricated" failure class (gap #3, U002).
3. **[S, high impact, protects 1 & 2] Hand-calibrate the LLM judge against ~20-30 self-labeled
   transcripts** before trusting its rubric scores as a regression gate — compute raw agreement per
   dimension (C-REMEDY, C-SCOPE, etc.), and fix/re-word any dimension where the judge and your own read
   diverge. This is a prerequisite for every accuracy claim downstream, cheap, and currently entirely
   missing.
4. **[M, medium impact] Fix the FSM's missing "confirmed resolved" terminal state**
   (`chat/orchestrator.py::_specialist_step`/`_advance`) — already root-caused in the gap analysis
   (#1) and independently corroborated in v2-validation §2 (H2, the dominant verdict). This is a
   product/FSM fix, not a retrieval fix, but it's the largest single contributor to the "0%
   resolvable" appearance in eval numbers and should land before further retrieval tuning is judged.
5. **[S, low-medium impact] Rebalance the eval persona language mix toward expected real Swedish
   traffic share** and, once real conversations exist, start mining real transcripts into the golden
   set rather than relying solely on synthetic personas (the sim's inability to play a resolve arc,
   fixed mid-sprint per v2-validation §2, is exactly the class of gap real transcripts sidestep).

Ponytail check: items 1, 3, 5 are pure config/process (no new code); item 2 adds one output field to
an existing call; item 4 is the one architecture-touching fix, and it's already independently
identified as the top root cause by the project's own gap analysis — this research doesn't add new
scope beyond what's already tracked, and actively argues against building RAG infrastructure (chunking,
hybrid search, reranker, knowledge graph) that the corpus size doesn't justify.
