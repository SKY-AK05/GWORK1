# DeepResearchAgent

A research pipeline built on **LangChain**, **LangGraph**, and **LangSmith**.
It turns an open-ended question into an evidence-backed report with explicit claims, confidence labels, and source-agreement scores.
Runs now emit inspectable Markdown artifacts plus styled export assets when available: `final_report.pdf`, `final_report.tex`, and `architecture_diagram.png`.

Two execution modes:

**Single researcher** (default):
```
detect_mode → plan_search → execute_searches → fetch_pages
           → build_memo → build_report → save_artifacts
```

**Multi-researcher** (`--num-researchers N`):
```
detect_mode → plan_researchers → execute_parallel_research [N concurrent]
           → build_report → save_artifacts
```

Each step is a **LangGraph node**. Every LLM call and state transition is automatically traced in **LangSmith**.

---

## Architecture

### Pipeline nodes

| Node | Mode | Role |
|---|---|---|
| `detect_mode` | both | Classifies task as *standard* or *comparison*; extracts comparison targets via regex or LLM |
| `plan_search` | single | Generates 2–5 search queries (count controlled by `--depth`) |
| `execute_searches` | single | Runs queries in parallel; deduplicates URLs |
| `fetch_pages` | single | Fetches markdown for each URL concurrently (Firecrawl → Crawl4AI fallback) |
| `follow_up_searches` | single | Asks LLM to identify gaps, generates 2–3 targeted follow-up queries, fetches additional pages |
| `build_memo` | single | Calls `LLM.with_structured_output(ResearchMemo)` to synthesise evidence, key statistics, and key quotes |
| `plan_researchers` | multi | Decomposes task into N focused sub-topics (always includes a counter-evidence angle) |
| `execute_parallel_research` | multi | Runs N researchers concurrently; each does search → fetch → follow-up → (RAG trim) → memo |
| `build_report` | both | Synthesises memo(s) into a `WriterReport` with thematic sections, narrative prose, recommendations, and confidence summary; deduplicates evidence across researchers |
| `critique` | both | Critic agent reviews draft report against source memos; flags unsupported claims, missing topics, contradictions |
| `save_artifacts` | both | Writes memo/report Markdown plus export artifacts: `final_report.pdf`, `final_report.tex`, and `architecture_diagram.png` when a Mermaid diagram is present |

The `critique` node creates a revision loop: if significant issues are found and `revision_count < 2`, the graph routes back to `build_report` for one revision pass before saving.

### LLM provider support

All LLM calls go through `src/llm/factory.py → get_llm("provider/model")`:

| Prefix | Backend |
|---|---|
| `openrouter/…` | OpenRouter API (pass the full OpenRouter model ID after the slash, e.g. `openrouter/gemini-3-flash-preview`) |
| `openai/…` | OpenAI API |
| `anthropic/…` | Anthropic API |
| `google/…` | Google Gemini (native) |

### Structured outputs

All LLM-heavy nodes use LangChain's `.with_structured_output()` — no manual JSON parsing. The Pydantic schemas live in `src/schemas/research.py`:

- `ResearchMemo` — researcher → writer handoff: sources, evidence bullets, summary, open questions, **key statistics**, **key quotes**, **source quality notes**
- `ReportSection` — one thematic section: title, **narrative prose** (2-4 paragraphs), structured claims, key statistics
- `WriterReport` — final output: **thematic sections** with narrative, **recommendations**, **methodology notes**, **confidence summary**, optional comparison table / Mermaid diagram
- `CritiqueResult` — critic output: unsupported claims, missing topics, contradictions, improvement notes

### RAG context engineering (`--rag`)

When `--rag` is set, each researcher trims its fetched pages before the memo LLM call:

1. Pages are split into 800-token overlapping chunks (`src/rag/chunker.py`)
2. The top-K most relevant chunks are retrieved (`src/rag/retriever.py`):
   - **FAISS + OpenAI embeddings** when `OPENAI_API_KEY` is set
   - **BM25** (`rank_bm25`) otherwise — no API key required
3. Only the retrieved chunks reach the LLM

**When RAG pays off**: fetched content > ~40k tokens (typical for multi-researcher runs with many pages). RAG cuts context ~80%, preventing overflow and reducing LLM cost proportionally.

**When to skip `--rag`**: small tasks where all content fits easily in context, or tasks requiring holistic cross-document synthesis (RAG can miss connections that span page boundaries).

### Memory management

Every run is backed by a typed memory layer (`src/memory/`) that caches expensive intermediate results and persists run provenance.

#### Data types

| Type | Backend | TTL | What it stores |
|---|---|---|---|
| `EPHEMERAL` | In-process dict | none | Task analysis, routing decisions |
| `SEARCH_RESULT` | Shared disk | 12 h | Web search results, keyed by normalized query |
| `PAGE_CACHE` | Shared disk | 24 h | Fetched page content, keyed by URL |
| `INTERMEDIATE` | Session disk | none | Researcher memos, critique results |
| `REPORT` | Session disk | none | Writer report drafts (versioned `report_v1`, `report_v2`) |
| `SESSION` | Session disk | none | Run provenance (task, model, depth, timestamp) |

`SEARCH_RESULT` and `PAGE_CACHE` are **shared across all runs** so a URL or query cached by one research task is immediately available to future tasks.  The three session types are scoped to a single run.

#### Storage layout

```
~/.cache/deepresearch/       (override with DEEPRESEARCH_CACHE_DIR env var)
├── search/                  # SEARCH_RESULT — query hash → results JSON (TTL 12 h)
├── page/                    # PAGE_CACHE    — URL hash → page JSON (TTL 24 h)
└── sessions/
    └── {session_id}/        # one directory per unique (task, model, depth, N) tuple
        ├── session/         # SESSION metadata
        ├── intermediate/    # INTERMEDIATE: memo(s), critique
        └── report/          # REPORT: report_v1.json, report_v2.json (if revised)
```

The user-facing `workdir/<tag>/` directory contains **only final artifacts** (`final_report.md`, `researcher_memo*.md`, `final_report.pdf`, `architecture_diagram.png`).  All cache and session data lives separately under `~/.cache/deepresearch/`.

#### Session identity and checkpoint recovery

The `session_id` is derived deterministically from `sha256(task + model + depth + num_researchers)[:16]`.  Running the same command again after a failure reuses the same `session_id`, so any page content or search results that were already fetched and cached are not re-fetched.

#### Design choices and trade-offs

The rationale behind the memory layer's design choices and its known limitations is documented separately in [docs/design-summary.md](docs/design-summary.md#memory-layer-design-choices-and-trade-offs).

---

## Repository Layout

```
scripts/
  run_mvp_research_system.py      # main entry point
  run_multi_researcher_example.py # multi-researcher demo
  evaluate_final_report.py        # offline report scorer

src/
  exporters/
    pdf.py                        # WriterReport -> LaTeX -> final_report.pdf (+ debug .tex)
    diagram.py                    # Mermaid -> architecture_diagram.png via mermaid.ink
  llm/
    factory.py                    # get_llm("provider/model")
  schemas/
    research.py                   # ResearchMemo, WriterReport Pydantic models
  tools/
    web_search.py                 # LangChain BaseTool → Tavily → Firecrawl → DDGS
    web_fetch.py                  # LangChain BaseTool → Firecrawl → Crawl4AI
  graph/
    state.py                      # ResearchState TypedDict
    nodes.py                      # all node functions (single + multi-researcher)
    graph.py                      # build_research_graph() → CompiledStateGraph
  memory/
    types.py                      # DataType enum, MemoryRecord dataclass
    manager.py                    # MemoryManager (async API + per-URL locks + query normalizer)
    backends/
      in_memory.py                # EPHEMERAL: in-process dict with TTL
      disk.py                     # SEARCH_RESULT/PAGE_CACHE/INTERMEDIATE/REPORT/SESSION: JSON files
  rag/
    chunker.py                    # RecursiveCharacterTextSplitter wrapper
    retriever.py                  # FAISS (primary) + BM25 fallback retriever
  evaluation/
    report_quality.py             # OfflineReportEvaluator (rubric via LLM)
    langsmith_eval.py             # run_langsmith_evaluation() for dataset eval

  tool/default_tools/search/      # Tavily, Firecrawl, DDGS backends (internal)
  utils/url_utils.py              # fetch_url() with Firecrawl/Crawl4AI/PDF fallback

docs/
  design-summary.md
```

---

## Installation

### 1. Create a conda environment

```bash
conda create -n DeepResearchAgent python=3.11
conda activate DeepResearchAgent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up Crawl4AI browser support

Crawl4AI is the fallback web fetcher when Firecrawl is unavailable. Run once after install:

```bash
crawl4ai-setup
playwright install chromium
crawl4ai-doctor
```

### 4. Install PDF export support

PDF export uses `xelatex` from TeX Live. On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y texlive-xetex texlive-fonts-recommended texlive-latex-extra
```

If `xelatex` is missing, the run still completes and writes Markdown artifacts; PDF generation just fails non-fatally.

### 5. Configure API keys

```bash
cp .env.template .env
```

Edit `.env`:

```env
# Required — default model routes through OpenRouter
OPENROUTER_API_KEY=your-key-here

# Required only if you switch to openai/ or anthropic/ models
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=

# Optional Azure AI Foundry OpenAI-compatible deployment
AZURE_AI_API_KEY=
AZURE_AI_ENDPOINT=https://<resource>.services.ai.azure.com/openai/v1
AZURE_AI_DEPLOYMENT=gpt-5.4-mini

# Optional — Firecrawl gives better scraping quality than the free DDGS fallback
FIRECRAWL_API_KEY=
TAVILY_API_KEY=

# Optional — enables semantic RAG (BM25 is used automatically when absent)
# OPENAI_API_KEY=   ← already listed above; set it to enable FAISS retrieval

# LangSmith tracing
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=DeepResearchAgent
```

To use Azure for this project, set those values locally and select `--model azure/gpt-5.4-mini`. The AI key powers model-backed planning, permitted tool-category selection, follow-up gap analysis, memo/report synthesis, claim verification, and critique. It is not a search-engine key, registry key, or browser-session credential. `COMPANIES_HOUSE_API_KEY` remains a separate optional credential for UK registry checks.

The browser helper in `src/browser/authorized.py` is opt-in and consent-gated. It opens the platform's normal login page in a temporary Playwright context; the user enters credentials directly there. The application never accepts passwords, exports cookies/storage state, sends session tokens to the model, bypasses CAPTCHA/MFA/OTP/paywalls, or accesses private messages. Persistent browser state requires explicit configuration and is disabled by default. If browser access is unavailable or cancelled, the public-source workflow continues and records the limitation.

---

## Run

### Single researcher (default)

```bash
python scripts/run_mvp_research_system.py \
  --task "Compare LangGraph, CrewAI, and AutoGen. Include a comparison table." \
  --tag demo_run
```

### Multi-researcher for comprehensive topics

```bash
python scripts/run_mvp_research_system.py \
  --task "What are the key challenges and breakthroughs in LLM efficiency?
          Cover training, inference optimization, and model compression." \
  --num-researchers 3 \
  --rag \
  --tag llm-efficiency
```

The planner decomposes the task into 3 sub-topics. Each researcher runs its own search → fetch → memo pipeline concurrently, then the writer synthesises all three memos into one final report.

### Flags

| Flag | Default | Description |
|---|---|---|
| `--task` | *(required)* | Research question |
| `--tag` | `mvp_research_system` | Subfolder under `workdir/` |
| `--model` | `openrouter/gemini-3-flash-preview` | LLM in `provider/model` format |
| `--workdir` | `workdir/<tag>` | Override output directory |
| `--num-researchers` | `1` | Parallel researchers (>1 enables multi-researcher mode) |
| `--rag` | off | Enable RAG context trimming before memo LLM calls |
| `--depth` | `standard` | `brief` (2 queries, 3 pages), `standard` (3 queries, 4 pages + 2 follow-up), `comprehensive` (5 queries, 6 pages + 3 follow-up + critic revision) |

### Switching models

```bash
# Anthropic Claude (direct)
--model anthropic/claude-sonnet-4-5

# OpenAI GPT-4o (direct)
--model openai/gpt-4o

# Any OpenRouter model — prefix with openrouter/ then the OpenRouter model ID
--model openrouter/gemini-3-flash-preview
--model openrouter/anthropic/claude-3.5-haiku
--model openrouter/meta-llama/llama-3.3-70b-instruct
```

### Output files (written to `workdir/<tag>/`)

Single researcher:
- `researcher_memo.md` — search plan, sources, evidence bullets, open questions
- `final_report.md` — executive summary, claims with confidence + source-agreement labels
- `final_report.pdf` — styled PDF export compiled from the structured `WriterReport`
- `final_report.tex` — LaTeX source written beside the PDF for debugging/customisation
- `architecture_diagram.png` — rendered Mermaid diagram when the writer includes an architecture diagram

Multi-researcher:
- `researcher_memo_1.md` … `researcher_memo_N.md` — one memo per parallel researcher
- `final_report.md` — synthesised across all N memos
- `final_report.pdf` / `final_report.tex` — same export pipeline as single-researcher mode
- `architecture_diagram.png` — generated when the final report includes Mermaid diagram output

The PNG is written to the run directory as `architecture_diagram.png` (for example `workdir/arc-compare/architecture_diagram.png`) and is embedded into the PDF when present.

---

## Evaluation

Score a generated report with a separate judge model:

```bash
python scripts/evaluate_final_report.py \
  --report-path workdir/demo_run/final_report.md \
  --judge-model openai/gpt-4o
```

Writes beside the report:

- `report_evaluation.json` — structured rubric scores
- `report_evaluation.md` — human-readable breakdown

**Rubric dimensions:** task alignment, coverage, evidence grounding, factual consistency, clarity/structure, actionability.

### Batch evaluation with LangSmith datasets

```python
from src.evaluation.langsmith_eval import run_langsmith_evaluation

results = run_langsmith_evaluation(
    dataset_name="deep-research-eval",
    examples=[
        {"task": "What is RAG?"},
        {"task": "Compare LangGraph vs AutoGen"},
    ],
    model_name="openrouter/gemini-3-flash-preview",
    judge_model="openai/gpt-4o",
)
```

Results appear in the LangSmith UI under the configured project name.

---

## Viewing Traces in LangSmith

Enable in `.env`:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__your_key_here
LANGCHAIN_PROJECT=DeepResearchAgent
```

Then run normally — every node, LLM call, and state transition streams to LangSmith automatically.

### What the trace looks like

**Single-researcher run:**
```
▼ CompiledStateGraph.invoke
  ▼ detect_mode               ← standard vs comparison
    └─ ChatOpenAI             ← LLM call (comparison tasks only)
  ▼ plan_search               ← generate queries (2-5 based on --depth)
    └─ ChatOpenAI
  ▶ execute_searches          ← web search (no LLM)
  ▶ fetch_pages               ← page fetching (no LLM)
  ▼ follow_up_searches        ← gap analysis + 0-3 follow-up fetches
    └─ ChatOpenAI             ← skipped for --depth brief
  ▼ build_memo                ← synthesise ResearchMemo (+ stats, quotes)
    └─ ChatOpenAI.with_structured_output(ResearchMemo)
  ▼ build_report              ← produce WriterReport (sections + narrative)
    └─ ChatOpenAI.with_structured_output(WriterReport)
  ▼ critique                  ← review draft against memo evidence
    └─ ChatOpenAI.with_structured_output(CritiqueResult)
  [▼ build_report]            ← revision pass if issues found (max 1x)
  ▶ save_artifacts            ← write files (no LLM)
```

**Multi-researcher run:**
```
▼ CompiledStateGraph.invoke
  ▶ detect_mode
  ▼ plan_researchers          ← decompose into N sub-topics
    └─ ChatOpenAI
  ▼ execute_parallel_research ← N researchers run concurrently
    ▼ researcher_1 (sub-topic A)
      ▶ search + follow-up search + fetch
      └─ ChatOpenAI.with_structured_output(ResearchMemo)
    ▼ researcher_2 (sub-topic B)
      ...
    ▼ researcher_N (sub-topic N)
      ...
  ▼ build_report              ← deduplicate evidence, synthesise N memos into sections
    └─ ChatOpenAI.with_structured_output(WriterReport)
  ▼ critique                  ← review draft against all memos
    └─ ChatOpenAI.with_structured_output(CritiqueResult)
  [▼ build_report]            ← revision pass if issues found (max 1x)
  ▶ save_artifacts
```

For each LLM call you can inspect the full prompt, raw response, parsed Pydantic object, token usage, and latency.

---

## Phase 6 Web App

The repository now includes a dependency-light web application in `webapp/`. It keeps the existing research engine as the only deep-research implementation and adds a separate discovery gate, explicit entity selection, bounded background jobs, real job status, and allowlisted artifact downloads.

### Run locally

```bash
source /home/ubuntu/zerone-work/upstream/.venv/bin/activate
PYTHONPATH=. ZERONE_WEB_PORT=8787 python -m webapp.server
```

Open `http://127.0.0.1:8787`. The server inherits the existing AI, search, crawler, and registry environment variables. Credentials are never returned by `/api/config`, embedded in the frontend, or written to job logs.

The public API surface is:

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Safe service and research-engine health status |
| `GET /api/config` | Capability presence only; never values |
| `POST /api/discover` | Bounded source-backed discovery with pagination |
| `POST /api/research` | Starts research only for a previously returned candidate ID |
| `GET /api/jobs/:id` | Queued/running/completed/failed status and stage |
| `GET /api/jobs/:id/artifacts` | Allowlisted artifact inventory |
| `GET /api/jobs/:id/artifacts/:name` | Safe report/JSON/source download |

The known-company flow is deliberately discovery-first: typing does not launch research, and the backend returns `409` if a caller tries to start a job without selecting a candidate from discovery. Blank-name searches require a country plus a narrowing filter. Discovery results are labelled as bounded public coverage, not as an exhaustive national registry.

Discovery also performs conservative identity resolution. When records share country plus meaningful legal/brand/domain signals, the UI presents one identity group with a canonical selectable profile and an expandable “Other names and linked records” section. Strong shared identifiers can produce `confirmed_same_company`; weaker evidence produces `possible_same_company` and lists the missing proof, as with the ORCHVATE LLP / `orchvate.com` pair. Original candidate IDs, source URLs, and evidence are retained; uncertain records are never silently deleted or merged.

### Deployment

The service is deployment-ready on a Python host that can run a background worker and persistent job/artifact storage. Set `ZERONE_WEB_HOST`, `ZERONE_WEB_PORT`, and the separate AI/search/registry variables through the host secret manager. Do not use GitHub Pages for this backend because it cannot run Python jobs or protect provider credentials. For a production deployment, put the service behind HTTPS, replace the in-process worker with a durable queue, and persist `webapp/data/jobs` in private storage.

Phase 6 was locally tested and publicly verified in the sandbox at `https://8787-ikiddm8cbfwr8f25bm6wk-fe51947d.sg2.manus.computer`. This URL is temporary and is not a permanent production deployment.

## Company Research Agent Mode

The product research command treats a company name as a question, not as an established identity. It creates candidate entities, compares legal names, brands, subsidiaries, branches, locations, registrations, websites, and aliases, then records whether candidates are related, distinct, or unresolved. Name similarity alone is never sufficient for a merge.

The investigation plan covers business purpose and mission, business model, products, services, operations, customers, beneficiaries, partnerships, competitors, and industry. It also searches for founders and leadership, public workforce signals, joiners, departures, position changes, and job postings. Job evidence records the role, skills, location, and remote/hybrid/office arrangement when explicitly published; it does not infer current employment from stale profiles.

The structured memo and report expose `entity_relationships`, `business_analysis`, `workforce_signals`, `hiring_signals`, and `claim_ledger`. Important claims are classified as `verified_fact`, `secondary_claim`, `inference`, or `unknown`, with source references and evidence gaps. Adaptive follow-up planning prioritizes unresolved identity links, missing primary records, contradictory facts, and under-covered hiring or workforce questions.

### Durable research memory

Each run now uses an append-only SQLite company-memory database at `~/.cache/deepresearch/company_intelligence.sqlite3` by default. Override it with `--memory-db` or `COMPANY_MEMORY_DB`. The store keeps profiles, legal-entity observations, aliases, relationships, products, customers, people, role changes, dated events, claims, source URLs, evidence excerpts, retrieval timestamps, confidence, and verification status in separate structured tables. Historical observations are retained rather than overwritten.

Before planning, the agent retrieves prior source-linked findings and reports stale records (30 days by default), missing evidence, and conflicting claim values as explicit research gaps. Previous model output is never treated as a verified fact unless it is stored with a supporting source URL and evidence excerpt. Unsupported claims are not persisted.

The agent prioritizes public sources and permitted APIs, including public company pages and public social/search results. It does not request passwords, OTPs, cookies, or session exports. If a permitted authenticated platform workflow is ever added, authentication must occur on that platform’s normal login page with explicit user control; otherwise the run continues with public sources and records the limitation.

Example with a dedicated test database:

```bash
PYTHONPATH=. python -m app research \
  --company ORCHVATE --country India --depth comprehensive \
  --memory-db /tmp/orchvate-company-memory.sqlite3
```

The ORCHVATE India memory test covers identity observations, aliases, source-linked claims, historical retention, stale-finding detection, and contradictory-headquarters detection. Provider-backed live social integrations were not enabled in this acceptance run; public-source behavior was tested with deterministic fixtures and the existing configured research adapters.

---

## Testing

```bash
pytest
```

The single live test (`tests/test_report_evaluation.py`) patches `get_llm` so no real API call is made.

---

## Output Artifact Design

Each run leaves inspectable intermediate files:

- `researcher_memo*.md` — captures search intent, evidence, and open questions **before** the writer sees anything
- `final_report.md` — claims separated from evidence so reviewers can check each one independently
- `final_report.pdf` — presentation-ready export compiled with XeLaTeX
- `final_report.tex` — debug-friendly LaTeX source for the PDF
- `architecture_diagram.png` — rendered copy of the Mermaid architecture diagram when that output was requested
- Evaluation files score the final report after the fact with a different judge model

That artifact trail is why the two-stage design exists: failures are visible and locatable, rather than hidden inside a single long model response. LangSmith traces add a second layer of observability at the LLM-call level.

---

## Zerone Prospect Intelligence additions

This GWORK1 branch preserves the upstream LangGraph architecture and adds the reviewed P1–P4 company-intelligence work plus the India verification module:

- **Discovery without starting URLs:** company tasks receive bounded official-site, social, and registry queries and may follow safe same-site/allowlisted links.
- **Crawl4AI-first fallback path:** Crawl4AI handles page crawling and JavaScript rendering when Firecrawl is unavailable. Firecrawl remains optional and is never required by the intended workflow.
- **Evidence provenance:** sources retain platform, category, discovery method, access status, identity status, excerpts, and retrieval timestamps.
- **Verification:** UK Companies House outcomes distinguish `confirmed_match`, `possible_match`, `no_match_in_completed_searches`, and `inconclusive_verification`. India registries are represented conservatively and do not bypass CAPTCHA/OTP controls or claim undocumented APIs.
- **Reliability:** search retries are bounded, provider errors are redacted and preserved, successful pages are retained alongside failures, and incomplete runs produce auditable `partial` or `blocked` artifacts.
- **Database-ready JSON:** each completed report also writes `prospect.json` with `brand_name`, `official_domain`, `legal_entity_name`, `jurisdiction`, `registration_number`, `sources`, `evidence`, verification statuses, confidence, and unresolved questions.

### Recommended setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
crawl4ai-doctor
cp .env.example .env
```

`FIRECRAWL_API_KEY` and `TAVILY_API_KEY` are optional. With both absent, the agent uses its free DDGS search fallback and Crawl4AI page fetching. An LLM provider key is still required for planning and synthesis unless the pipeline is being exercised with mocked tests.

### ORCHVATE benchmark example

```bash
FIRECRAWL_API_KEY= TAVILY_API_KEY= COMPANIES_HOUSE_API_KEY= \
PYTHONPATH=. python scripts/run_mvp_research_system.py \
  --task "Investigate ORCHVATE as a company in the United Kingdom. Starting information: only the company name ORCHVATE and target jurisdiction United Kingdom." \
  --model openai/gpt-5-mini \
  --depth brief \
  --tag orchvate
```

The output directory contains `researcher_memo.md`, `final_report.md`, and the validated `prospect.json`. A missing Companies House key yields `inconclusive_verification`; it must not be interpreted as proof that the company is absent.

The original one-line GWORK1 README is preserved at [`docs/gwork1-original-readme.md`](docs/gwork1-original-readme.md).

### Product CLI

The supported product-facing command accepts the required company and country and writes a timestamped run directory:

```bash
python -m app research \
  --company "ORCHVATE" \
  --country "India" \
  --website "https://orchvate.com" \
  --depth comprehensive \
  --recent "last 12 months"
```

Outputs are written below `reports/<company-slug>/<UTC-timestamp>/` as `company_research_report.md`, `company_research.json`, `sources.json`, `run_metadata.json`, `prospect.json`, and `changes.json`. A latest snapshot is maintained under the company directory in `snapshots/latest.json`; change summaries distinguish newly observed fields from changed fields without treating observation time as event time. The CLI validates the four core product artifacts before reporting completion.

### Implementation status

The three delivery phases are pushed separately on `zerone-prospect-intelligence`: Phase 1 hardens public URL boundaries and adds SSRF/prompt-injection boundary tests; Phase 2 adds the product CLI and stable manifests; Phase 3 adds artifact validation, snapshots, change detection, and release documentation. Authenticated browser research is not enabled by the product CLI; the current core path uses public sources and reports login/access limitations rather than collecting passwords or cookies.
