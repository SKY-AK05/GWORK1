# Zerone Prospect Intelligence Release Notes

## Included

- Upstream deep-research LangGraph pipeline integrated into GWORK1.
- Discovery from only a company name and jurisdiction, including official-site, social, and registry query planning.
- Crawl4AI-first page fetching with optional Firecrawl fallback and graceful provider failure handling.
- Source provenance and identity-candidate records that distinguish brand evidence from legal-entity proof.
- UK Companies House verification outcomes with explicit `inconclusive_verification` semantics.
- India registry inventory and conservative identifier/name matching without CAPTCHA/OTP bypass or undocumented API claims.
- P4 reliability improvements: bounded retry, timeout classification, redacted errors, successful-result preservation, and partial-run artifacts.
- Validated `ProspectRecord` / `prospect.json` export for downstream storage.
- 28 passing tests covering the integrated reliability, provenance, company-intelligence, India, and JSON-contract behavior.

## Deliberate non-claims

- Social profiles do not prove legal incorporation.
- A missing registry credential does not prove that a company is absent.
- A brand/domain match does not automatically establish legal ownership or entity identity.
- Published emails and phone numbers remain unverified business contacts.
- CAPTCHA/OTP-protected portals are not automated around.
