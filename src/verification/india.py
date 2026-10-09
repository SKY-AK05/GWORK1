"""India-specific company and brand verification helpers.

This module deliberately does not scrape CAPTCHA/OTP-protected portals or claim a
public API that has not been documented and verified. Callers may inject permitted
records from official interfaces, downloadable datasets, or documented APIs.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


INDIA_REGISTRY_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "registry": "MCA company and LLP master data",
        "authority": "Ministry of Corporate Affairs, Government of India",
        "source_url": "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html",
        "access_method": "official public portal interface",
        "documented_public_api": False,
        "requires_identifier_for_targeted_verification": False,
        "access_constraints": "Portal presents user login/OTP and CAPTCHA controls; no anonymous REST API was confirmed in the reviewed official documentation.",
        "supported_entity_types": ["company", "LLP"],
    },
    {
        "registry": "Government Open Data India company master data catalog",
        "authority": "Government of India / NIC data.gov.in",
        "source_url": "https://www.data.gov.in/catalog/company-master-data",
        "access_method": "official open-data catalog",
        "documented_public_api": "not_confirmed",
        "requires_identifier_for_targeted_verification": False,
        "access_constraints": "Catalog page was accessible, but no current downloadable resource or API contract was confirmed during this implementation.",
        "supported_entity_types": ["company"],
    },
    {
        "registry": "GST taxpayer search",
        "authority": "Goods and Services Tax Network / Government of India",
        "source_url": "https://tutorial.gst.gov.in/userguide/taxpayersdashboard/Search_Taxpayer_manual.htm",
        "access_method": "official pre-login portal search",
        "documented_public_api": False,
        "requires_identifier_for_targeted_verification": True,
        "access_constraints": "Official manual documents lookup by GSTIN/UIN and CAPTCHA; name-only lookup is not treated as available.",
        "supported_entity_types": ["company", "LLP", "proprietorship", "partnership", "other taxpayer"],
    },
    {
        "registry": "Udyam MSME verification",
        "authority": "Ministry of Micro, Small and Medium Enterprises, Government of India",
        "source_url": "https://udyamregistration.gov.in/Udyam_Verify.aspx",
        "access_method": "official verification portal",
        "documented_public_api": False,
        "requires_identifier_for_targeted_verification": True,
        "access_constraints": "Verification is identifier-driven; no documented public API was confirmed. CAPTCHA or other portal controls must be respected.",
        "supported_entity_types": ["enterprise", "proprietorship", "company", "LLP", "partnership"],
    },
    {
        "registry": "Indian Trade Marks Registry public search",
        "authority": "IP India / CGPDTM, Government of India",
        "source_url": "https://tmrsearch.ipindia.gov.in/tmrpublicsearch/",
        "access_method": "official public trademark search",
        "documented_public_api": False,
        "requires_identifier_for_targeted_verification": False,
        "access_constraints": "Public search page presents OTP and CAPTCHA controls; trademark ownership is evidence of an application/registration, not proof of business operation.",
        "supported_entity_types": ["trademark applicant/owner"],
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_india_name(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\b(private limited|pvt ltd|pvt|private ltd|limited|ltd|llp|llp\.|incorporated|inc)\b", " ", value)
    return " ".join(value.split())


def normalize_identifier(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def classify_india_identifier(value: Optional[str]) -> Optional[str]:
    """Classify common identifiers without asserting that the identifier is valid."""
    identifier = normalize_identifier(value)
    if not identifier:
        return None
    if re.fullmatch(r"[ULFOTCGP][0-9]{5}[A-Z]{2}[0-9]{4}PLC[0-9]{6}", identifier):
        return "CIN"
    if re.fullmatch(r"[A-Z]{3}[0-9]{4}", identifier):
        return "LLPIN_candidate"
    if re.fullmatch(r"[0-9]{2}[A-Z0-9]{5}[0-9]{4}[A-Z][A-Z0-9][Z][A-Z0-9]", identifier):
        return "GSTIN_candidate"
    if re.fullmatch(r"UDYAM[A-Z]{2}[0-9]{2}[0-9]{7}", identifier):
        return "Udyam_candidate"
    return "unknown"


def india_name_variants(name: str, aliases: Iterable[str] = ()) -> list[str]:
    values: list[str] = []
    for value in (name, *aliases):
        value = " ".join(str(value).split())
        if value and value not in values:
            values.append(value)
        normalized = normalize_india_name(value)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _record(*, registry: str, source_url: str, query: Optional[str], candidate: dict[str, Any], rationale: str, retrieved_at: Optional[str] = None) -> dict[str, Any]:
    identifier = candidate.get("identifier") or candidate.get("cin") or candidate.get("llpin") or candidate.get("gstin") or candidate.get("udyam_number")
    identifier_type = candidate.get("identifier_type") or classify_india_identifier(identifier)
    return {
        "registry": registry,
        "source_url": source_url,
        "retrieved_at": retrieved_at or _now(),
        "search_query": query,
        "identifier": identifier,
        "identifier_type": identifier_type,
        "legal_name": candidate.get("legal_name") or candidate.get("name"),
        "entity_type": candidate.get("entity_type", "unknown"),
        "status": candidate.get("status"),
        "incorporation_date": candidate.get("incorporation_date"),
        "registered_office": candidate.get("registered_office"),
        "officers": candidate.get("officers", []),
        "matching_rationale": rationale,
        "confidence": candidate.get("confidence", "medium"),
        "verification_status": candidate.get("verification_status", "candidate"),
    }


def match_india_candidate(target_name: str, candidate: dict[str, Any], *, registry: str, source_url: str, query: Optional[str] = None, aliases: Iterable[str] = (), retrieved_at: Optional[str] = None) -> dict[str, Any]:
    """Match a legal candidate while keeping brands and similar names separate."""
    target_names = {normalize_india_name(x) for x in india_name_variants(target_name, aliases)}
    legal_name = str(candidate.get("legal_name") or candidate.get("name") or "")
    candidate_name = normalize_india_name(legal_name)
    identifier = candidate.get("identifier") or candidate.get("cin") or candidate.get("llpin")
    entity_type = str(candidate.get("entity_type", "unknown")).lower()
    exact_name = bool(candidate_name and candidate_name in target_names)
    identifier_confirmed = bool(candidate.get("identifier_confirmed") or candidate.get("authoritative_match"))
    is_brand_or_mark = entity_type in {"brand", "trademark", "trademark_owner"}
    if is_brand_or_mark:
        status, confidence, rationale = "possible_match", "low", "Trademark/brand evidence is not legal-entity proof."
    elif identifier_confirmed and exact_name:
        status, confidence, rationale = "confirmed_match", "high", "Authoritative record identifier and legal-name variant match the target."
    elif exact_name or (candidate_name and any(candidate_name in n or n in candidate_name for n in target_names)):
        status, confidence, rationale = "possible_match", "medium", "Legal-name similarity was observed, but an authoritative identifier or relationship is not sufficient for confirmation."
    else:
        status, confidence, rationale = "rejected", "high", "Candidate name does not match the supplied Indian legal-name variants."
    result = _record(registry=registry, source_url=source_url, query=query, candidate=candidate, rationale=rationale, retrieved_at=retrieved_at)
    result.update({"target_name": target_name, "match_status": status, "confidence": confidence})
    result["verification_status"] = "verified" if status == "confirmed_match" else "unverified"
    return result


def classify_india_registry_outcome(*, registry: str, attempted: bool, records: list[dict[str, Any]], queries: list[str], identifiers: list[str], error: Optional[str] = None, source_url: Optional[str] = None) -> dict[str, Any]:
    if error or not attempted:
        outcome = "inconclusive_verification"
    elif any(r.get("match_status") == "confirmed_match" for r in records):
        outcome = "confirmed_match"
    elif any(r.get("match_status") == "possible_match" for r in records):
        outcome = "possible_match"
    else:
        outcome = "no_match_in_completed_searches"
    return {
        "registry": registry,
        "source_url": source_url,
        "outcome": outcome,
        "records": records,
        "searched_name_variants": queries,
        "searched_identifiers": identifiers,
        "error": error,
        "retrieved_at": _now(),
        "verification_status": "verified" if outcome == "confirmed_match" else "unverified",
    }


def build_india_verification(name: str, *, aliases: Iterable[str] = (), identifiers: Iterable[str] = (), candidate_records: Optional[dict[str, list[dict[str, Any]]]] = None, attempted_registries: Optional[set[str]] = None) -> dict[str, Any]:
    """Build a modular India verification result from permitted records only.

    `candidate_records` is intentionally injected by a caller that has obtained
    records through an allowed official interface, downloadable dataset, or verified
    documented API. This function itself performs no CAPTCHA or portal bypass.
    """
    queries = india_name_variants(name, aliases)
    ids = [normalize_identifier(x) for x in identifiers if normalize_identifier(x)]
    candidate_records = candidate_records or {}
    attempted_registries = attempted_registries or set()
    results: dict[str, Any] = {"jurisdiction": "India", "target_name": name, "name_variants": queries, "identifiers": ids, "registry_inventory": list(INDIA_REGISTRY_SOURCES), "registries": {}, "retrieved_at": _now()}
    for source in INDIA_REGISTRY_SOURCES:
        registry = source["registry"]
        raw = candidate_records.get(registry, [])
        records = [match_india_candidate(name, item, registry=registry, source_url=source["source_url"], query=item.get("query") or name, aliases=aliases) for item in raw]
        attempted = registry in attempted_registries
        error = None
        if not attempted and not raw:
            error = "No permitted registry query was executed; source requires portal interaction or an identifier/API not configured."
        results["registries"][registry] = classify_india_registry_outcome(registry=registry, attempted=attempted or bool(raw), records=records, queries=queries, identifiers=ids, error=error, source_url=source["source_url"])
    return results
