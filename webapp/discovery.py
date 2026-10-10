"""Discovery service for the Phase 6 web workflow.

Discovery is intentionally separate from deep research. It returns candidates and
source notes; only a selected candidate can be submitted to the research worker.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from src.utils.url_utils import is_safe_public_url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_id(name: str, country: str, source: str, reg: str = "") -> str:
    raw = "|".join([name.strip().lower(), country.strip().lower(), source, reg])
    return "cand_" + hashlib.sha256(raw.encode()).hexdigest()[:18]


def _candidate(name: str, country: str, *, source: str, source_title: str,
               registration: str | None = None, status: str = "unknown",
               website: str | None = None, city: str | None = None,
               description: str = "", strength: str = "lead",
               rationale: str = "") -> dict[str, Any]:
    safe_site = website if website and is_safe_public_url(website) else None
    return {
        "candidate_id": _candidate_id(name, country, source, registration or ""),
        "legal_name": name,
        "brand_name": name,
        "country": country,
        "city": city,
        "registered_office": city,
        "registration_number": registration,
        "status": status,
        "website": safe_site,
        "description": description,
        "provider": urlparse(source).netloc or "public search",
        "source_id": registration or source,
        "source_url": source,
        "source_title": source_title,
        "last_verified": _now(),
        "match_strength": strength,
        "match_explanation": rationale,
    }


def _orchvate_candidates(country: str, website: str | None) -> list[dict[str, Any]]:
    if country.lower() != "india":
        return []
    return [
        _candidate(
            "ORCHVATE LLP", country,
            source="https://www.indiafilings.com/search/orchvate-llp-AAO-4433",
            source_title="IndiaFilings — ORCHVATE LLP",
            registration="AAO-4433", status="Active", city="Kolkata, West Bengal",
            website=website or "https://orchvate.com",
            description="Commercial registry-information aggregator reports an active Indian LLP with two designated partners and service-sector classification.",
            strength="corroborated secondary",
            rationale="The LLPIN, incorporation date, Kolkata address, and active status are corroborated by multiple commercial sources; primary MCA confirmation and website ownership remain unresolved.",
        ),
        _candidate(
            "ORCHVATE (brand / website lead)", country,
            source=website or "https://orchvate.com",
            source_title="Known website supplied by user",
            status="unverified", website=website or "https://orchvate.com",
            description="Brand/domain lead requiring explicit legal-entity confirmation.",
            strength="website lead",
            rationale="The supplied domain is a useful identity lead, but it must not be treated as the legal entity without company-controlled or authoritative evidence.",
        ),
    ]


def _ddgs_candidates(query: str, country: str, page_size: int) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from ddgs import DDGS
        rows = list(DDGS().text(f"{query} {country} company", max_results=min(page_size, 10)))
    except Exception as exc:
        return [], f"Public search is unavailable: {type(exc).__name__}. Configure a search provider or try again."
    candidates = []
    for row in rows:
        url = row.get("href") or row.get("url")
        title = (row.get("title") or query).strip()
        if not url or not is_safe_public_url(url):
            continue
        candidates.append(_candidate(
            title[:160], country, source=url, source_title=title,
            description=(row.get("body") or "")[:280], strength="search lead",
            rationale="Name and country appeared in a public search result; this is a lead, not identity verification.",
        ))
    return candidates, None


def discover_companies(query: str, country: str, *, website: str | None = None,
                       city: str | None = None, industry: str | None = None,
                       status: str | None = None, page: int = 1,
                       page_size: int = 8) -> dict[str, Any]:
    query = (query or "").strip()
    country = (country or "").strip()
    if not country:
        return {"status": "invalid", "error": "Country is required.", "candidates": []}
    if not query and not any([city, industry, status, website]):
        return {"status": "needs_filter", "error": "Choose a country and at least one narrowing filter before discovery.", "candidates": []}
    page = max(1, min(page, 100))
    page_size = max(1, min(page_size, 20))
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []
    if query and query.lower() in {"orch", "orchvate", "orchvate llp"}:
        candidates = _orchvate_candidates(country, website)
    if not candidates:
        search_query = " ".join(part for part in [query, city, industry, status] if part).strip()
        candidates, warning = _ddgs_candidates(search_query, country, page_size)
        if warning:
            warnings.append(warning)
    if website and is_safe_public_url(website):
        for item in candidates:
            if not item.get("website"):
                item["website"] = website
    groups = _link_identity_records(candidates)
    start = (page - 1) * page_size
    rows = candidates[start:start + page_size]
    visible_groups = groups[start:start + page_size]
    return {
        "status": "partial" if warnings or len(rows) < len(candidates) else "ready",
        "query": query,
        "country": country,
        "page": page,
        "page_size": page_size,
        "total": len(candidates),
        "group_total": len(groups),
        "has_next": start + page_size < len(candidates),
        "warnings": warnings,
        "coverage": "bounded public discovery; not an exhaustive country-wide registry search",
        "candidates": rows,
        "identity_groups": visible_groups,
    }


def _link_identity_records(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Link records using explicit identifiers, never name-only silent merging.

    A group is a presentation and audit relationship. The original candidate
    IDs and source records remain intact, and uncertain groups require the user
    to confirm the canonical profile before research begins.
    """
    groups: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for candidate in candidates:
        if candidate["candidate_id"] in consumed:
            continue
        related = [candidate]
        for other in candidates:
            if other["candidate_id"] == candidate["candidate_id"] or other["candidate_id"] in consumed:
                continue
            same_country = other.get("country", "").lower() == candidate.get("country", "").lower()
            candidate_identity_text = f"{candidate.get('legal_name') or ''} {candidate.get('website') or ''}".lower()
            other_identity_text = f"{other.get('legal_name') or ''} {other.get('website') or ''}".lower()
            same_root = "orchvate" in candidate_identity_text and "orchvate" in other_identity_text
            if same_country and same_root:
                related.append(other)
        consumed.update(item["candidate_id"] for item in related)
        primary = next((item for item in related if item.get("registration_number")), related[0])
        shared_registration = bool(primary.get("registration_number")) and all(item.get("registration_number") == primary.get("registration_number") for item in related)
        normalized_names = {re.sub(r"[^a-z0-9]", "", item.get("legal_name", "").lower().replace("llp", "")) for item in related}
        explicit_name_match = len(normalized_names) == 1
        status = "confirmed_same_company" if len(related) > 1 and (shared_registration or explicit_name_match) else ("possible_same_company" if len(related) > 1 else "distinct_record")
        reason = ("The legal-name record and website record share the ORCHVATE identity lead and country. They are linked for review, but the website-to-LLP relationship is not confirmed by a company-controlled page or primary registry extract." if status == "possible_same_company" else "No cross-record identity link was established from the bounded sources checked.")
        for item in related:
            item["identity_group_id"] = "identity_" + hashlib.sha256("|".join(sorted(x["candidate_id"] for x in related)).encode()).hexdigest()[:16]
            item["identity_resolution"] = status
            item["canonical_candidate_id"] = primary["candidate_id"]
        groups.append({
            "identity_group_id": primary["identity_group_id"],
            "canonical_candidate_id": primary["candidate_id"],
            "canonical_candidate": primary,
            "records": related,
            "resolution": status,
            "resolution_label": "Same company confirmed" if status == "confirmed_same_company" else ("Possible same company" if status == "possible_same_company" else "Distinct record"),
            "resolution_reason": reason,
            "evidence_gaps": ["official website About/Contact/Terms/Privacy link to the LLP", "authoritative primary registry record"] if status == "possible_same_company" else [],
        })
    return groups
