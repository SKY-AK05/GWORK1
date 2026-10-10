# Phase 6 Plan — Zerone Prospect Intelligence Web App

## Product outcome

Add a responsive, discovery-first web application to the existing Python research engine. Users can search for a company, review source-backed candidates, explicitly select one, start a bounded research job, observe real status, and download the resulting report and machine-readable artifacts.

## Architecture

- `webapp/`: small Python HTTP application with JSON APIs and a static responsive frontend.
- Existing `src/` research engine: remains the only research implementation.
- Discovery service: adapter-backed public search/registry lookup with stable candidate IDs, source URLs, match rationale, and explicit partial/unavailable states.
- Job service: in-process bounded background worker for local/deployment-ready execution; job records retain queued/running/partial/completed/failed status and artifact names, never arbitrary filesystem paths.
- Artifact endpoint: allowlisted artifacts only, resolved beneath the job directory after path validation.
- `public/manus-routes.json`: route declaration for the web surface.

## Design direction

- **Movement:** editorial intelligence console—quiet, evidence-led, and operational rather than a generic SaaS dashboard.
- **Principles:** provenance first; progressive disclosure; calm status clarity; decisive candidate selection.
- **Color philosophy:** near-black ink and warm paper create research-room focus; electric cyan marks active evidence and actions; amber marks partial/unresolved findings without implying failure.
- **Layout:** asymmetric split-screen workspace: a narrow command rail and a broad evidence canvas, collapsing into a single-column mobile flow.
- **Signature elements:** evidence chips with source counts; thin cyan route lines; status timeline with explicit state labels.
- **Interaction:** typing/searching only discovers; explicit selection is the gate before expensive research. Empty, partial, and unavailable states explain the next action.
- **Typography:** system sans for controls and readable serif/display accents for report framing; high-contrast focus states and keyboard-first controls.
- **Brand essence:** a careful prospect-intelligence workspace for teams who need traceable company research, not confident guesses. Personality: precise, calm, candid.
- **Voice:** direct and evidence-aware. Example lines: “Select the entity before we spend the research budget.” and “Partial is a valid result when the public record is incomplete.”
- **Mark:** a small cyan bracket enclosing a dot—an entity under evidence review.
- **Signature color:** electric cyan `#59e1e8`.

## Required behavior

1. Discovery API runs before research and returns source-backed candidate cards.
2. Partial-name and known-company searches are paginated and bounded.
3. Blank company name requires country plus a narrowing filter.
4. Research creation requires a selected candidate ID; no name-only deep research endpoint.
5. Job polling reports real state and stage messages.
6. Artifact downloads expose only allowlisted files.
7. SSRF, unsafe URLs, XSS, path traversal, malformed input, and secret leakage are tested.
8. Existing Phase 5 research behavior remains unchanged; ORCHVATE India gets a focused mocked integration smoke test rather than an unnecessary full live rerun.
9. The local server is deployment-ready with documented environment variables and a public sandbox URL if the runtime is available.
