# ORCHVATE Benchmark Comparison

## Same task

The untouched upstream baseline and the integrated branch were run with the same ORCHVATE/United Kingdom task, `openai/gpt-5-mini`, brief depth, and no Firecrawl, Tavily, or Companies House API keys. The runner has a pre-existing shell-wrapper bug: `PIPESTATUS[0]` becomes empty after the `tee` pipeline, so the wrapper prints `exit: numeric argument required` even after the application has generated its artifacts. The application output, not that wrapper error, is the benchmark result.

## Observed results

| Measure | Untouched baseline | Integrated branch |
|---|---:|---:|
| Unique URLs in researcher memo | 6 | 14 in the first integrated run; 14 in the final run |
| Evidence-bearing source pages | 1 official website page in the baseline run | 4 pages in the final run: two official-site pages plus Facebook and Instagram |
| Search/fetch failure records | Failures were reported but not represented as structured memo fields | Bounded retry records and explicit fetch-failure records are preserved in the memo/report |
| Registry result | No registry verification field | `inconclusive_verification`; explicit `COMPANIES_HOUSE_API_KEY is not configured` note |
| Run status | No structured partial-run status | `partial`, with search and fetch failures retained |
| Machine-readable storage output | Markdown/PDF-oriented artifact flow | Validated `prospect.json` plus Markdown/PDF-oriented artifact flow |
| Integrated unit tests | Upstream baseline suite recorded separately | **28 passed** after the prospect export was added |

## Final integrated record

The final benchmark wrote [`prospect.json`](benchmarks/final/prospect.json) with:

- `brand_name`: `ORCHVATE`
- `official_domain`: `orchvate.com`
- `legal_entity_name`: `null`
- `jurisdiction`: `United Kingdom` (task target, not a verified incorporation jurisdiction)
- `registration_number`: `null`
- `identity_match_status`: `possible_match`
- `registration_verification_status`: `inconclusive_verification`
- `confidence`: `medium`
- 4 source records, 16 evidence records, and 5 unresolved questions

The report correctly concludes that ORCHVATE is an observable operating brand with an official website and social presence, while the available material does not prove a UK-incorporated legal entity. It does **not** turn an absent API key or a failed fetch into a negative legal conclusion.

## Known limitations

- The Companies House API key was intentionally absent for this benchmark; a later run with a valid key can upgrade the registry status.
- Crawl4AI fetched official pages in the final run, but some page URLs can still be blocked or timeout-dependent.
- The optional PDF export remains non-fatal when XeLaTeX is not installed; Markdown and JSON are still produced.
