# DeepResearchAgent — Improvement Log

Tracks proposed improvements: rationale, affected files, and status.

---

## Implemented

### #2 — Human-in-the-loop checkpoint after `plan_search`
**Status:** ✅ Done  
**Trigger:** `--interactive` CLI flag  
**What it does:** Pauses execution after `plan_search` (single-researcher) or `plan_researchers` (multi-researcher) so the user can review and edit the proposed query plan or sub-topic list before any web fetches begin.  
**How:** `build_research_graph(interactive=True)` compiles with `MemorySaver` and `interrupt_after=["plan_search", "plan_researchers"]`. `_run_interactive()` in the run script calls `ainvoke()` twice — once to reach the checkpoint, once to resume after optional `update_state()`.  
**Key files:**
- `src/graph/graph.py` — `build_research_graph(interactive=False)`
- `scripts/run_mvp_research_system.py` — `_run_interactive()`, `--interactive` flag

---

### #3 — Per-node model routing (`--writer-model`)
**Status:** ✅ Done  
**Trigger:** `--writer-model provider/model` CLI flag (optional; falls back to `--model`)  
**What it does:** Routes lightweight planning nodes (query generation, gap analysis, task detection) to a cheap/fast research model, and synthesis nodes (memo building, report writing, critique, claim verification) to a stronger writer model. Typical use: `--model openrouter/google/gemini-2.0-flash-lite-001 --writer-model openrouter/google/gemini-2.5-flash`.  
**How:** Two helpers `_research_llm(state)` and `_writer_llm(state)` replace all direct `get_llm(state["model_name"])` calls. `_run_single_researcher` accepts a `writer_model_name` param and uses separate LLM instances for query gen vs. memo building.  
**Key files:**
- `src/graph/nodes.py` — `_research_llm()`, `_writer_llm()`
- `src/graph/state.py` — `writer_model_name: Optional[str]`
- `scripts/run_mvp_research_system.py` — `--writer-model` flag

---

### #4 — Claim-level source verification node
**Status:** ✅ Done (cost-gated: skipped on revision passes and for `brief` depth)  
**Position in graph:** `build_report → verify_claims → critique`  
**What it does:** After the first report draft, identifies claims with `confidence=Low` or `source_agreement=Insufficient evidence/Conflicting` (capped at 5). For each, resolves the `[N]` citation to a source URL, re-fetches the page (almost always a PAGE_CACHE hit), and asks the writer LLM whether the content actually supports the claim. Failed verifications are injected into the critique prompt as hard evidence, forcing `has_issues=True` with those claims in `unsupported_claims`.  
**Key files:**
- `src/schemas/research.py` — `SourceVerdict`, `ClaimVerificationResult`
- `src/graph/nodes.py` — `verify_claims_node()`, `_url_for_citation()`
- `src/graph/state.py` — `verification_results: Optional[List[dict]]`
- `src/graph/graph.py` — `verify_claims` node wired between `build_report` and `critique`

---

## Pending

### #1 — Iterative researcher loop with open-question closure
**Priority:** High  
**What:** `ResearchMemo.open_questions` identifies gaps but nothing acts on them. Add a loop-back edge from `build_memo` to `fetch_pages` when open questions exceed a threshold, triggering additional targeted searches.  
**Trade-off:** Adds latency for comprehensive depth; needs a max-iteration guard.  
**Key files to change:** `src/graph/graph.py`, `src/graph/nodes.py:follow_up_searches_node`, `src/graph/state.py` (add `open_question_iteration: int`)

---

### #5 — Semantic query deduplication
**Priority:** Medium  
**What:** Search cache keys are exact normalized strings — two queries with the same intent but different wording hit the API separately. Embed each query and check cosine similarity against cached query embeddings before issuing a new search; reuse the cached result if similarity > threshold.  
**Trade-off:** Requires an embedding call per query; BM25 overlap could serve as a zero-cost approximation.  
**Key files to change:** `src/memory/manager.py:search_cache_key()`, `src/graph/nodes.py:execute_searches_node`

---

### #6 — Cross-run memo retrieval
**Priority:** Medium  
**What:** Memos from past sessions are never reused. Index `ResearchMemo` objects in a persistent vector store (keyed by task embedding) and retrieve relevant past memos at `build_memo_node` time to seed the writer with prior knowledge on related topics.  
**Trade-off:** Significant scope increase; stale memos could introduce outdated information — TTL or recency-weighting required.  
**Key files to change:** `src/memory/manager.py`, `src/rag/retriever.py`, `src/graph/nodes.py:build_memo_node`

---

### #7 — LLM output caching on re-runs
**Priority:** Medium  
**What:** Structured LLM outputs (memos, report drafts) are already written to the session store but never read back to *skip* re-execution. Check whether a memo/report already exists in `INTERMEDIATE`/`REPORT` before calling the LLM; return cached result if present and `--force-refresh` is not set.  
**Trade-off:** Stale cache after source content changes; needs explicit invalidation or TTL.  
**Key files to change:** `src/graph/nodes.py:build_memo_node`, `src/graph/nodes.py:build_report_node`, `scripts/run_mvp_research_system.py` (`--force-refresh` flag)

---

### #8 — Hardcoded adversarial researcher role
**Priority:** Medium  
**What:** `plan_researchers_node` includes a counter-evidence angle as a soft prompt convention. Hardcode one researcher slot as an explicit devil's advocate with a dedicated system prompt instructing it to find contradictory evidence, known failures, and published criticisms — regardless of the main task framing.  
**Trade-off:** Minimal overhead; may surface irrelevant criticism for uncontroversial topics.  
**Key files to change:** `src/graph/nodes.py:plan_researchers_node`, `src/graph/nodes.py:_run_single_researcher`

---

### #9 — Cross-researcher evidence deduplication at memo stage
**Priority:** Low–Medium  
**What:** `_deduplicate_memos()` removes duplicate evidence bullets but the writer still receives all N full memos. Merge overlapping sources into a shared evidence pool before the writer call to reduce prompt size and give the writer a cleaner view.  
**Trade-off:** Loses the per-researcher framing that gives the writer context about which sub-topic each piece of evidence came from.  
**Key files to change:** `src/graph/nodes.py:_deduplicate_memos()`, `src/graph/nodes.py:build_report_node`

---

### #10 — Streaming progress output to CLI
**Priority:** Low–Medium  
**What:** The CLI is silent until `save_artifacts`. Use LangGraph's `astream_events` API to surface real-time node transitions (queries issued, pages fetched, memo building, etc.) without changing graph logic.  
**Trade-off:** Adds complexity to the run script; useful mainly for long `comprehensive` depth runs.  
**Key files to change:** `scripts/run_mvp_research_system.py:main()` (replace `ainvoke` with `astream_events`)

---

### #11 — Automated regression tests for graph nodes
**Priority:** Low–Medium  
**What:** Only one test exists (`test_report_evaluation.py`). The highest-risk nodes — `execute_searches_node`, `fetch_pages_node`, `build_memo_node`, `verify_claims_node` — have no tests. Add unit tests with pre-canned fixture data (stored search results, fetched pages) that exercise node logic without live API calls.  
**Trade-off:** Fixture maintenance burden; mocked LLM outputs may not catch prompt-regression issues.  
**Key files to change:** `tests/` (new test files per node group)

---

### #12 — Portable PDF export (replace xelatex)
**Priority:** Low  
**What:** The current PDF pipeline requires `xelatex` + specific fonts and fails silently when missing. Replace with a Python-native renderer (`weasyprint` or `reportlab`) for portable, dependency-free PDF output.  
**Trade-off:** LaTeX produces higher-quality typesetting; `weasyprint` requires CSS knowledge for layout.  
**Key files to change:** `src/exporters/pdf.py`

---

### #13 — RAG embedding provider abstraction
**Priority:** Low  
**What:** `src/rag/retriever.py` hard-codes `text-embedding-3-small` (OpenAI). Wire the embedding model through the LLM factory or add a `--embedding-model` flag so the system works without an OpenAI key for embeddings.  
**Trade-off:** Minor scope; only matters when `--rag` is used without an OpenAI key.  
**Key files to change:** `src/rag/retriever.py`, `scripts/run_mvp_research_system.py` (`--embedding-model` flag)

---

### #14 — Configurable revision budget (`--max-revisions`)
**Priority:** Low  
**What:** `revision_count < 2` is hardcoded in `_route_after_critique`. Expose `--max-revisions` as a CLI flag and propagate it through `ResearchState` so users can trade output quality for latency.  
**Trade-off:** More revisions add proportional LLM cost with diminishing quality returns.  
**Key files to change:** `src/graph/graph.py:_route_after_critique()`, `src/graph/state.py`, `scripts/run_mvp_research_system.py`

---

### #15 — Source credibility scoring
**Priority:** Low  
**What:** `ResearchSource.source_quality_notes` is free text. Assign a numeric credibility tier (peer-reviewed > official docs > news > blog > unknown) based on domain heuristics and propagate the score into `ClaimRecord.confidence` so evidence grounding is more systematic.  
**Trade-off:** Heuristic domain classification is brittle; vendor docs score high but can be biased.  
**Key files to change:** `src/schemas/research.py:ResearchSource`, `src/graph/nodes.py:build_memo_node`
