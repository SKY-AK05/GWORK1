# Uploaded ZIP Recovery Report

## Scope

All ZIP archives uploaded through the temporary multi-file staging page were extracted into a separate inspection area. The original ZIPs and their contents were not modified. The destination repository was then rebuilt from the untouched upstream baseline and the reviewed source snapshots were integrated into branch `zerone-prospect-intelligence`.

## Bundles processed

| Bundle | Purpose | Validation evidence |
|---|---|---|
| `orchvate_company_intelligence_p1_bundle` | P1 social discovery, provenance, baseline audit, implementation report, benchmark memo/report, source patch, and provenance test | README reports 5 tests, `compileall`, and `git diff --check` passed |
| `orchvate_company_intelligence_p3_bundle` | P3 company-intelligence verification helpers, source-provenance tests, cumulative tracked changes, and benchmark materials | Reviewed company-intelligence and provenance tests plus cumulative patch metadata |
| `orchvate_company_intelligence_p4_bundle` | P4 reliability work: bounded retries, timeout/failure records, fetch splitting, schema support, cumulative source snapshot, tests, and benchmark materials | 4 P4 reliability/provenance tests integrated and passing |
| `orchvate_india_verification_bundle` | Conservative India registry/identifier helpers, India tests, cumulative India source snapshot, and P4 test copies | 7 India verification tests integrated and passing |

The full extracted file-by-file manifest is preserved in [`zip-contents-manifest.txt`](zip-contents-manifest.txt).

## Patch recovery

The uploaded `.patch` files contained terminal ANSI color escape sequences because they were captured from a colored Git diff. That made `git apply` report “no valid patches.” Temporary sanitized copies were created by removing only ANSI color codes; the uploaded artifacts remained unchanged. The sanitized cumulative P4 patch applied cleanly to the untouched upstream baseline. The India patch also applied cleanly to the same baseline, but it was a cumulative baseline patch rather than a delta after P4.

Because the tracked patches did not include every new verification module, the final integration used the reviewed complete source snapshots from the P4 and India bundles for:

- `src/graph/graph.py`
- `src/graph/nodes.py`
- `src/graph/state.py`
- `src/schemas/research.py`
- `src/tools/web_fetch.py`
- `src/tools/web_search.py`
- `src/verification/company_intelligence.py`
- `src/verification/india.py`
- `src/verification/__init__.py`

The destination also includes the reviewed cumulative tests and a new regression test for the validated `prospect.json` export.

## Safety and secret handling

No archive contents were copied into the application as credentials. No secret-like values were found in the integrated source scan. `.env`, `.venv`, caches, logs, and `workdir/` are ignored. Provider keys remain optional/configured through environment variables only.

## Integration result

- Destination branch: `zerone-prospect-intelligence`
- Original destination content preserved at `docs/gwork1-original-readme.md`
- Integrated tests after the JSON export: **28 passed**, one non-blocking dependency deprecation warning
- Python `compileall`: passed
- Final benchmark: generated Markdown reports and a schema-validated `prospect.json`
