# Phase 5 Acceptance — ORCHVATE + India

## Run identity

| Field | Result |
|---|---|
| Repository | `SKY-AK05/GWORK1` |
| Branch | `zerone-prospect-intelligence` |
| Starting remote SHA | `95cb3204e88e0fdf35e5c8fd55bdb865237ac51e` |
| Acceptance fix commit before final run | `6aadec69fe49bf0305730d7c4ab669663b398f1d` |
| Final acceptance run ID | `57628e24e72593e0` |
| Model | Azure AI Foundry OpenAI-compatible deployment `gpt-5.4-mini` |
| Depth | `comprehensive` |
| Run status | `partial` in metadata; CLI completed successfully with exit code 0 |
| Artifact validation | Passed |
| Authentication | No authenticated browser session used |

Exact command, with secrets omitted:

```bash
python -m app research \
  --company "ORCHVATE" \
  --country "India" \
  --website "https://orchvate.com" \
  --depth comprehensive \
  --recent "last 12 months" \
  --model azure/gpt-5.4-mini \
  --output-dir /home/ubuntu/zerone-work/phase5-final-runs
```

## Live AI verification

The final run made successful live model calls through the configured Azure deployment. Safe metadata records successful calls for `TaskAnalysis`, `ResearchPlan`, `ResearchMemo`, `WriterReport`, and `CritiqueResult`; it also records the bounded report-revision pass. No prompt, model output, API key, cookie, or session token is stored in the telemetry.

The first acceptance attempt exposed an Azure strict-schema incompatibility with open-ended dictionary fields. The application was changed to use function-calling structured output for compatible providers, all 40 regression tests passed, and the final live run completed with `CLI_EXIT=0`.

## Actual tools used

- **DDGS web search:** used for public discovery; metadata records 12 planned/executed queries, 15 search results, and 9 search failures/retries.
- **Crawl4AI:** used for accessible public pages; metadata records 7 fetched pages and 2 fetch failures.
- **Companies House:** called with the configured UK credential as a foreign-registry cross-check; no match was returned. This is not evidence about Indian incorporation.
- **Firecrawl:** not configured; correctly reported unavailable.
- **Authenticated browser:** not used. No password, cookie, private profile, private message, CAPTCHA, MFA, OTP, paywall, or access restriction was bypassed.

## Adaptive research

The comprehensive run produced a model-generated research plan and a larger executed query set covering legal identity, domain attribution, services, social discovery, hiring, registry cross-checking, and follow-up identity queries. The run remained within the configured bounded workflow and preserved 9 search failures and 2 fetch failures rather than converting them into negative company claims. The most important unresolved gap after follow-up was the missing direct verification of `orchvate.com` and the lack of a primary Indian registry extract.

## Coverage table

| Category | Result | Evidence/source references | Limitations |
|---|---|---|---|
| Identity and website | Partial | [1], [2], [3]; known domain `orchvate.com` | LLP identity is corroborated, but the website could not be fetched successfully and its legal ownership is unresolved. |
| Indian legal registration | Inconclusive | [1], [2], [3] | Three commercial aggregators agree on ORCHVATE LLP, LLPIN `AAO-4433`, 05 Mar 2019, Kolkata, and active status; no primary MCA extract was obtained. |
| Products/services | Unresolved/partial | [2], [3] | Sources support broad service-sector classification; no verified company-owned product/service page was available in the final run. |
| Customers/partnerships | Unresolved | No supporting source in final set | No named customers, case studies, or partnerships were verified. |
| Leadership/workforce | Partial | [2], [3] | Two designated partners are reported; employee count, team structure, and workforce growth were not verified. |
| Hiring/work model | Unresolved | No supporting source in final set | No verified current job listing or reliable remote/hybrid/office signal was found. |
| Recent changes | Unresolved | No primary dated company source in final set | The requested 12-month operational timeline could not be reconstructed reliably. |
| Social presence | Unresolved | Search plan includes public social queries; no verified profile source in final set | No official LinkedIn, Instagram, Facebook, X, YouTube, or hashtag evidence was independently confirmed. |
| Trends/competitors | Partial | Report analysis section | Industry-level interpretation is clearly labelled as analysis; company-specific competitive evidence is limited. |

## Main evidence result

The strongest supported conclusion is that the target likely corresponds to **ORCHVATE LLP**, an Indian LLP with LLPIN **AAO-4433**, incorporated on **05 March 2019**, associated with Kolkata, West Bengal, and reported as active by multiple commercial registry aggregators. This is **corroborated secondary evidence**, not primary government-registry verification.

The final record deliberately does **not** claim that `orchvate.com` is legally operated by ORCHVATE LLP. It also does not treat the Companies House no-match result as evidence against Indian existence.

## Output files

- [`company_research_report.md`](company_research_report.md)
- [`company_research.json`](company_research.json)
- [`sources.json`](sources.json)
- [`run_metadata.json`](run_metadata.json)
- [`prospect.json`](prospect.json)
- [`changes.json`](changes.json)
- [`researcher_memo.md`](researcher_memo.md)
- [`architecture_diagram.png`](architecture_diagram.png)

## Source references

1. [ORCHVATE LLP — Tracxn](https://tracxn.com/d/legal-entities/india/orchvate-llp/__nrTVcvejjdzdnl9LXCWEvL1c2Dhay2WTw_K6vz6ITn4) — commercial aggregator; partial public access.
2. [ORCHVATE LLP — The Company Check](https://www.thecompanycheck.com/company/orchvate-llp/AAO-4433) — commercial aggregator; partial public access.
3. [ORCHVATE LLP — IndiaFilings](https://www.indiafilings.com/search/orchvate-llp-AAO-4433) — commercial registry-information aggregator; partial public access.

## Capability labels

- `implemented_and_live_tested`: Azure model routing, structured AI planning, report synthesis, critique/revision, DDGS search, Crawl4AI fetching, Companies House cross-check, artifact validation, and public-source ORCHVATE India run.
- `implemented_mocked_only`: consent-gated browser helper and persistent-session safeguards.
- `implemented_not_integrated`: authenticated browser helper is not part of the default CLI graph.
- `blocked_missing_credentials_or_permissions`: primary MCA extraction and authenticated social research were not available in this run.
- `not_implemented`: CAPTCHA/MFA/OTP/paywall bypass and private-profile/private-message research.
