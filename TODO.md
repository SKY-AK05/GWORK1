# Phase 6 Outcomes

- Deliver a responsive Zerone Prospect Intelligence website where users enter company, country, optional website/city, depth, and recent period; entering a name alone never starts deep research.
- Run bounded company discovery first, display source-backed candidate entities with stable IDs, provider IDs, locations, status, domains, descriptions, timestamps, match strength, and rationale; require explicit candidate selection before research.
- Support partial-name search such as `Orch`, pagination, no-match refinement guidance, blank-name narrowing filters, and clear unavailable/missing-provider states without fabricating candidates or claiming exhaustive country coverage.
- Start research only for the selected candidate, preserve the existing research engine, report queued/running/partial/completed/failed states and meaningful stage updates, and expose report, JSON, sources, metadata, prospect, and changes artifacts through safe downloads.
- Preserve legal entity, brand, website, parent/subsidiary, branch, and similar-name distinctions; represent Indian primary MCA verification as unavailable or inconclusive unless an authoritative query succeeds.
- Retain SSRF protections, safe redirects, unsafe-scheme blocking, input validation, XSS-safe rendering, path traversal protection, bounded retries/timeouts, artifact isolation, no arbitrary LLM tools, and no frontend secrets.
- Add deterministic tests for ORCHVATE India discovery-before-research, ORCHVATE UK registry scope, partial-name pagination, blank-name refusal, ambiguous selection, provider outage, unsafe URLs, XSS-safe rendering, job states, artifact allowlists, and secret scanning.
- Update README, environment placeholders, architecture/deployment instructions, run focused tests, push to `zerone-prospect-intelligence`, verify the remote SHA, and report whether deployment is local-tested, deployed, or publicly verified.
