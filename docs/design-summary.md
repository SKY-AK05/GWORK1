# Design Summary

## Architecture

The system is a directed pipeline implemented as a **LangGraph StateGraph**. All state flows through a single `ResearchState` TypedDict. Nodes read from it and return partial dict updates; LangGraph merges them before the next node runs.

```
START
  → detect_mode        classify task; extract comparison targets
  → plan_search        generate search queries via LLM
  → execute_searches   run queries in parallel; deduplicate URLs
  → fetch_pages        fetch markdown content concurrently
  → build_memo         LLM synthesises ResearchMemo (structured output)
  → build_report       LLM produces WriterReport (structured output)
  → save_artifacts     write researcher_memo.md + final_report.md
END
```

All LLM calls use LangChain's `.with_structured_output(PydanticModel)` — no JSON extraction code. Every call and state transition is automatically traced in **LangSmith** when `LANGCHAIN_TRACING_V2=true`.

## Key Design Decisions

### 1. Separation of evidence gathering from synthesis

The researcher node and writer node see different things on purpose. The researcher sees raw webpage content. The writer only sees the structured `ResearchMemo`. This makes it possible to debug failures: if the final report is wrong, you can open `researcher_memo.md` and check whether the problem came from bad search results, bad page content, or bad synthesis.

### 2. Structured outputs throughout

Both LLM-heavy nodes use `with_structured_output()` rather than prompting the model to return JSON and then parsing it. If the model returns malformed output, LangChain retries automatically. The Pydantic schemas in `src/schemas/research.py` define the contract between stages.

`ResearchMemo` carries:
- `question`, `task_mode`, `comparison_targets`, `requested_outputs`
- `search_plan` (queries executed)
- `sources` — list of `ResearchSource(title, url, evidence[])` 
- `summary`, `open_questions`

`WriterReport` carries:
- `executive_summary`
- `claims` — list of `ClaimRecord(claim, confidence, source_agreement, evidence[])`
- optional `comparison_table_markdown`, `architecture_diagram_mermaid`
- `open_questions`, `sources`

### 3. Explicit uncertainty

Claims carry two labels — `confidence` (High / Medium / Low) and `source_agreement` (Strong agreement / Mixed / Conflicting / Insufficient evidence). A reader can see at a glance which claims are well-supported and which are not. The writer is explicitly told not to smooth uncertainty away.

### 4. LangSmith for observability

Cost tracking, token counts, latency, and prompt inspection are handled by LangSmith rather than custom logging. This replaces the previous hand-written `| 💰 Usage:` log format. Set `LANGCHAIN_TRACING_V2=true` in `.env` and every run appears in the LangSmith project dashboard with a full node-by-node trace tree.

### 5. Tool architecture

Web tools (`WebSearchTool`, `WebFetchTool` in `src/tools/`) are standard LangChain `BaseTool` subclasses. They wrap the existing Firecrawl and DDGS backends from `src/tool/default_tools/search/`. Graph nodes call tools via `.ainvoke()` directly — there is no agentic tool-use loop. This keeps the pipeline deterministic and easy to test.

### 6. Multi-provider LLM support

`get_llm("provider/model")` in `src/llm/factory.py` creates the right LangChain chat model for any supported provider. Switching models is a single `--model` flag with no other code changes required.

## What Is Intentionally Excluded

- Orchestrator / planner agent
- Verifier / critic pass
- Iterative refinement loops (the pipeline runs once)
- Long-term memory across runs
- Self-evolving prompts or agents
- RL policy updates

These are excluded to keep the demo reliable and the failure modes legible. The two-stage pipeline produces inspectable artifacts at each step; adding more agents without that artifact trail would make debugging harder.

## Future Directions

- **Verifier node** — a third LLM pass that checks each claim against the raw source URLs before the report is written
- **Iterative researcher** — loop back from the memo to fetch additional sources for open questions
- **LangSmith dataset evaluation** — use `run_langsmith_evaluation()` in `src/evaluation/langsmith_eval.py` to score batches of tasks against a fixed rubric
- **Human-in-the-loop** — use LangGraph's interrupt/resume to let a user approve or redirect the search plan before fetching pages

## Memory layer design choices and trade-offs

**Why content-addressed disk files instead of a database?**
The workload is read-heavy with large values (page content up to 100 KB each).  A flat directory of JSON files keyed by `sha256(key)[:24]` gives O(1) lookup without a running process, survives process crashes, and is trivially inspectable.  A SQLite or Redis store would add operational complexity without meaningful throughput benefit at this scale.

**Why asyncio.to_thread() for disk I/O?**
All node functions are `async`.  Calling `json.load/dump` synchronously would block the event loop during parallel researcher runs, serialising what should be concurrent fetches.  `asyncio.to_thread()` offloads each read/write to the default thread pool executor, keeping the event loop free.

**Why per-URL asyncio.Lock for page fetching?**
In multi-researcher mode, N researchers run concurrently via `asyncio.gather`.  Without a lock, two researchers targeting the same URL would both find a cache miss and both issue a network request.  `get_or_fetch_page(url, fetch_fn)` uses **double-checked locking**: a fast unlocked check first, then acquire the per-URL lock and re-check, then fetch.  The second coroutine to arrive always reads from cache rather than duplicating the network call.

**Why normalize search query keys?**
Search queries are generated independently by each researcher's LLM call.  Minor surface differences ("LangGraph agents" vs "langgraph  agents") would produce different SHA-256 hashes and bypass the cache.  `search_cache_key(query)` lowercases and collapses whitespace before hashing, improving hit rates for near-duplicate queries without changing what is sent to the search API.

**Why FIFO eviction rather than LRU?**
True LRU requires updating access-time metadata on every read, which adds a disk write to every cache hit and doubles I/O.  FIFO eviction (delete oldest by mtime when the directory exceeds `MAX_ENTRIES`) is one write-time scan with no read overhead.  For a research cache where entries are typically used once per session, FIFO approximates LRU closely enough.  Caps: 500 search entries, 200 page entries (configurable in `src/memory/backends/disk.py`).

**Why EPHEMERAL for task analysis?**
`detect_mode` output (task mode, comparison targets, requested outputs) is cheap to recompute and has no value persisting across process restarts.  Storing it in the in-process `InMemoryBackend` makes it queryable within the same run (e.g., by a future introspection tool or sub-graph) without touching disk.

### Known limitations

- *Semantic deduplication*: cache keys are exact-match (normalised string hash).  Two queries with the same intent but different wording will each hit the search API.  Embedding-based deduplication would improve this but requires a running vector store.
- *Cross-run knowledge accumulation*: researcher memos from past runs are not fed into future runs.  A persistent vector store of past `ResearchMemo` objects (indexed by question and topic) would enable this but is out of scope.
