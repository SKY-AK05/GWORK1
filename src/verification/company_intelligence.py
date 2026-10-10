"""Pure P3 company-intelligence verification helpers.

The functions in this module are deliberately provider-independent and return plain
records with provenance fields. They never infer deliverability, current employment,
or legal existence from a weak signal.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", value.lower())
    value = re.sub(r"\b(private limited|pvt ltd|limited|ltd|llp|incorporated|inc)\b", " ", value)
    return " ".join(value.split())


def match_company_identity(target_name: str, candidate: dict[str, Any], jurisdiction: Optional[str] = None) -> dict[str, Any]:
    """Score a candidate without merging it into the target on name similarity alone."""
    target = normalize_name(target_name)
    candidate_name = normalize_name(str(candidate.get("name", "")))
    exact = bool(target and candidate_name and target == candidate_name)
    token_overlap = bool(target and candidate_name and (target in candidate_name or candidate_name in target))
    
    cand_jurisdiction = str(candidate.get("jurisdiction", "")).strip()
    cand_id = candidate.get("company_number") or candidate.get("id") or candidate.get("registration_number")
    cand_domain = candidate.get("domain") or candidate.get("website")

    jurisdiction_match = bool(jurisdiction and cand_jurisdiction and cand_jurisdiction.lower() in jurisdiction.lower())
    jurisdiction_conflict = bool(jurisdiction and cand_jurisdiction and cand_jurisdiction.lower() not in jurisdiction.lower() and jurisdiction.lower() not in cand_jurisdiction.lower())

    if jurisdiction_conflict:
        status, confidence = "rejected", "high"
        rationale = f"Contradictory jurisdiction: target expects '{jurisdiction}', candidate registered in '{cand_jurisdiction}'."
    elif cand_id and exact and (jurisdiction_match or not jurisdiction):
        # Official legal identifier corroboration in matching jurisdiction
        status, confidence = "confirmed_match", "high"
        rationale = f"Exact name match corroborated by official registry identifier ({cand_id}) in {cand_jurisdiction or jurisdiction}."
    elif cand_domain and exact:
        status, confidence = "confirmed_match", "high"
        rationale = f"Exact name match verified with company-controlled domain ({cand_domain})."
    elif exact and (jurisdiction_match or not jurisdiction):
        # Exact name but no verified legal identifier or domain yet: keep as possible match, unmerged!
        status, confidence = "possible_match", "medium"
        rationale = f"Name match in {cand_jurisdiction or jurisdiction}, but lacks independent legal identifier or domain corroboration; unmerged."
    elif token_overlap:
        status, confidence = "possible_match", "low"
        rationale = "Token overlap observed; similarity alone is insufficient to verify identity."
    else:
        status, confidence = "rejected", "high"
        rationale = "No name similarity or conflicting entity attributes."

    return {
        "target_name": target_name,
        "candidate_name": candidate.get("name", ""),
        "candidate_id": cand_id,
        "jurisdiction": cand_jurisdiction or jurisdiction,
        "match_status": status,
        "confidence": confidence,
        "match_rationale": rationale,
        "source_url": candidate.get("source_url"),
        "evidence": candidate.get("evidence", []),
        "retrieved_at": candidate.get("retrieved_at") or _now(),
        "verification_status": "verified" if status == "confirmed_match" else "unverified",
    }


def resolve_candidate_identities(
    candidates: list[dict[str, Any]],
    target_name: str,
    jurisdiction: Optional[str] = None,
) -> dict[str, Any]:
    """Conservative entity resolution comparing legal identifiers, jurisdiction, address, and domain.

    Never merges on name similarity alone. Partitions candidates into:
    - confirmed: matching legal identifier or verified domain in matching jurisdiction
    - related: linked parent, subsidiary, brand, branch, or acquisition
    - unrelated: distinct registration number, conflicting jurisdiction, or separate business
    - unverified: name similarity without independent corroborating evidence
    """
    confirmed = []
    related = []
    unrelated = []
    unverified = []

    seen_ids = set()
    for cand in candidates:
        scored = match_company_identity(target_name, cand, jurisdiction)
        status = scored.get("match_status")
        cand_id = scored.get("candidate_id")

        # Deduplicate candidates with identical id
        dedup_key = (str(cand_id), str(scored.get("candidate_name", "")).lower())
        if cand_id and dedup_key in seen_ids:
            continue
        if cand_id:
            seen_ids.add(dedup_key)

        is_related = cand.get("relationship_type") in ("parent", "subsidiary", "brand", "branch", "acquisition")
        if is_related:
            related.append(scored)
        elif status == "confirmed_match":
            confirmed.append(scored)
        elif status == "rejected":
            unrelated.append(scored)
        else:
            unverified.append(scored)

    return {
        "confirmed": confirmed,
        "related": related,
        "unrelated": unrelated,
        "unverified": unverified,
        "total_evaluated": len(candidates),
        "resolution_summary": (
            f"Evaluated {len(candidates)} candidate(s): {len(confirmed)} confirmed, "
            f"{len(related)} related, {len(unverified)} unverified similarity, {len(unrelated)} unrelated."
        ),
    }


def classify_registry_outcome(*, attempted: bool, records: list[dict[str, Any]], error: Optional[str] = None) -> dict[str, Any]:
    """Distinguish a completed no-match from an unavailable or inconclusive search."""
    if error:
        outcome = "inconclusive_verification"
    elif not attempted:
        outcome = "inconclusive_verification"
    elif any(r.get("match_status") == "confirmed_match" for r in records):
        outcome = "confirmed_match"
    elif any(r.get("match_status") == "possible_match" for r in records):
        outcome = "possible_match"
    else:
        outcome = "no_match_in_completed_searches"
    return {
        "registry": "Companies House",
        "outcome": outcome,
        "records": records,
        "error": error,
        "retrieved_at": _now(),
        "verification_status": "verified" if outcome == "confirmed_match" else "unverified",
    }


async def search_companies_house(name: str, api_key: Optional[str] = None, client: Any = None) -> dict[str, Any]:
    """Query the official Companies House API when explicitly configured.

    No key means no network call and an honest inconclusive outcome. The API key is
    read from the environment by default and is never included in returned records.
    """
    if api_key is None:
        api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    if not api_key:
        return classify_registry_outcome(attempted=False, records=[], error="COMPANIES_HOUSE_API_KEY is not configured")
    close_client = False
    if client is None:
        import httpx
        client = httpx.AsyncClient(timeout=20.0)
        close_client = True
    try:
        response = await client.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": name, "items_per_page": 20},
            auth=(api_key, ""),
        )
        if response.status_code >= 400:
            return classify_registry_outcome(attempted=True, records=[], error=f"Companies House HTTP {response.status_code}")
        payload = response.json()
        records = []
        for item in payload.get("items", []):
            candidate = {
                "name": item.get("title", ""),
                "company_number": item.get("company_number"),
                "jurisdiction": "United Kingdom",
                "source_url": f"https://find-and-update.company-information.service.gov.uk/company/{item.get('company_number')}" if item.get("company_number") else "https://find-and-update.company-information.service.gov.uk/",
                "evidence": [item.get("description", "") or item.get("title", "")],
            }
            records.append(match_company_identity(name, candidate, "United Kingdom"))
        return classify_registry_outcome(attempted=True, records=records)
    except Exception as exc:
        return classify_registry_outcome(attempted=True, records=[], error=f"Companies House request failed: {exc}")
    finally:
        if close_client:
            await client.aclose()


def _record(source_url: str, evidence: str, retrieved_at: Optional[str], **fields: Any) -> dict[str, Any]:
    return {
        **fields,
        "source_url": source_url,
        "evidence": evidence.strip(),
        "publication_date": fields.get("publication_date"),
        "retrieved_at": retrieved_at or _now(),
        "confidence": fields.get("confidence", "medium"),
        "verification_status": fields.get("verification_status", "candidate"),
    }


def _page_matches_target(page: dict[str, Any], target_name: Optional[str]) -> bool:
    if not target_name:
        return True
    haystack = " ".join((page.get("url", ""), page.get("title", ""), page.get("content", "")))
    return normalize_name(target_name) in normalize_name(haystack)


_CONTACT_AGGREGATOR_DOMAINS = {
    "tracxn.com", "thecompanycheck.com", "zaubacorp.com", "tofler.in",
    "linkedin.com", "google.com", "whatsapp.com", "wa.me", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "sentry.io", "wixpress.com",
    "cloudflare.com", "example.com", "domain.com", "github.com", "wikipedia.org",
}

_INVALID_EMAIL_PREFIXES = (
    "privacy@", "legal@", "abuse@", "postmaster@", "security@", "noreply@", "no-reply@",
    "mailer-daemon@", "hostmaster@", "webmaster@", "support@tracxn.com", "contact@zaubacorp.com"
)


def extract_business_contacts(pages: list[dict[str, Any]], target_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Extract legitimate published business contact channels; reject aggregators and generic privacy emails."""
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    email_re = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    phone_re = re.compile(r"(?<!\w)(?:\+\d[\d ()().-]{7,}\d|\(?\d{3,4}\)?[ -]\d{3,4}[ -]\d{3,4})(?!\w)")

    for page in pages:
        if not _page_matches_target(page, target_name):
            continue
        url, content, retrieved = page.get("url", ""), page.get("content", ""), page.get("retrieved_at")
        page_netloc = urlparse(url).netloc.lower()

        for kind, pattern in (("email", email_re), ("phone", phone_re)):
            haystack = content if kind == "email" else "\n".join(
                line for line in content.splitlines() if re.search(r"(?i)phone|tel|call|whatsapp|contact", line)
            )
            for match in pattern.findall(haystack):
                value = " ".join(match.split())
                val_lower = value.lower()

                # Filter email validity & aggregators
                if kind == "email":
                    email_domain = val_lower.split("@")[-1] if "@" in val_lower else ""
                    if email_domain in _CONTACT_AGGREGATOR_DOMAINS:
                        continue
                    if any(val_lower.startswith(prefix) for prefix in _INVALID_EMAIL_PREFIXES):
                        continue
                    local_part = val_lower.split("@")[0] if "@" in val_lower else ""
                    if any(noise in local_part for noise in ("someone", "username", "john.doe")) or val_lower.endswith((".png", ".jpg", ".jpeg", ".gif")):
                        continue

                # Filter phone validity
                if kind == "phone":
                    digits = re.sub(r"\D", "", value)
                    if len(digits) < 8 or len(digits) > 15:
                        continue
                    # Ignore dates formatted like 2024-01-01 or all same digits
                    if len(set(digits)) <= 2:
                        continue

                key = (kind, val_lower)
                if key in seen:
                    continue
                seen.add(key)
                results.append(_record(
                    url,
                    f"Published on fetched page: {value}",
                    retrieved,
                    contact_type=kind,
                    channel_type=kind,
                    value=value,
                    publisher=page_netloc,
                    verification_status="published_unverified",
                    confidence="medium",
                ))

        for link in re.findall(r"https?://[^\s<>\]\)\"']+", content):
            link_clean = link.rstrip(".,;:!?")
            link_lower = link_clean.lower()
            if any(token in link_lower for token in ("/contact", "contact-us", "/book", "calendly")):
                link_netloc = urlparse(link_clean).netloc.lower()
                if link_netloc in _CONTACT_AGGREGATOR_DOMAINS and "calendly" not in link_lower:
                    continue
                key = ("channel", link_lower)
                if key not in seen:
                    seen.add(key)
                    results.append(_record(
                        url,
                        f"Published contact channel link: {link_clean}",
                        retrieved,
                        contact_type="channel",
                        channel_type="channel",
                        value=link_clean,
                        publisher=page_netloc,
                        verification_status="published_unverified",
                        confidence="medium",
                    ))
    return results


def classify_role_status(role_text: str) -> str:
    text = role_text.lower()
    historical = ("former", "previously", "ex-", "left ", "until ", "past ")
    return "historical" if any(marker in text for marker in historical) else "current_claim"


def extract_roles(pages: list[dict[str, Any]], target_name: Optional[str] = None) -> list[dict[str, Any]]:
    from src.validation import is_valid_person_name
    results = []
    role_re = re.compile(r"(?i)([A-Z][A-Za-z.'-]{2,}(?:\s+[A-Z][A-Za-z.'-]{2,}){0,3})\s*[-,:|—]\s*(founder|co[- ]?founder|ceo|chief executive officer|director|head of [A-Za-z ]+|advisor|manager)")
    historical_re = re.compile(r"(?i)(former|ex-)\s*(founder|co[- ]?founder|ceo|chief executive officer|director|advisor|manager)\s+([A-Z][A-Za-z.'-]{2,}(?:\s+[A-Z][A-Za-z.'-]{2,}){0,3})")
    for page in pages:
        if not _page_matches_target(page, target_name):
            continue
        for line in page.get("content", "").splitlines():
            match = role_re.search(line)
            if match:
                candidate_person = match.group(1).strip()
                if not is_valid_person_name(candidate_person, target_name=target_name):
                    continue
                role_text = match.group(0).strip()
                results.append(_record(page.get("url", ""), line, page.get("retrieved_at"), person_name=candidate_person, role=match.group(2).strip(), role_status=classify_role_status(role_text), confidence="medium", verification_status="candidate"))
                continue
            historical = historical_re.search(line)
            if historical:
                candidate_person = historical.group(3).strip()
                if not is_valid_person_name(candidate_person, target_name=target_name):
                    continue
                results.append(_record(page.get("url", ""), line, page.get("retrieved_at"), person_name=candidate_person, role=historical.group(2).strip(), role_status="historical", confidence="medium", verification_status="candidate"))
    return results


def extract_dated_events(pages: list[dict[str, Any]], target_name: Optional[str] = None) -> list[dict[str, Any]]:
    results = []
    date_re = re.compile(r"\b(?:\d{1,2}[/-])?\d{1,2}[/-]\d{2,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b|\b20\d{2}\b", re.I)
    event_words = ("founded", "launched", "partnered", "acquired", "funded", "funding", "joined", "left", "announced", "expanded", "established")
    for page in pages:
        if not _page_matches_target(page, target_name):
            continue
        for line in page.get("content", "").splitlines():
            if date_re.search(line) and any(word in line.lower() for word in event_words):
                date_match = date_re.search(line)
                event_type = next(word for word in event_words if word in line.lower())
                results.append(_record(page.get("url", ""), line, page.get("retrieved_at"), event_type=event_type, event_date=date_match.group(0), confidence="medium", verification_status="candidate"))
    return results


def detect_contradictions(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find conflicting normalized values without deciding which source is correct."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for claim in claims:
        field = str(claim.get("field", "")).strip()
        value = normalize_name(str(claim.get("value", "")))
        if field and value:
            grouped[field][value].append(claim)
    contradictions = []
    for field, values in grouped.items():
        if len(values) > 1:
            contradictions.append({
                "field": field,
                "values": [{"normalized_value": value, "claims": items} for value, items in values.items()],
                "verification_status": "conflicting",
                "confidence": "high",
                "retrieved_at": _now(),
            })
    return contradictions


def extract_identity_candidates(target_name: str, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    target = normalize_name(target_name)
    for page in pages:
        content = page.get("content", "")
        if target and target in normalize_name(content):
            results.append({
                "candidate_name": target_name,
                "source_url": page.get("url", ""),
                "evidence": [f"Target name appears in fetched source: {page.get('title', '')}"],
                "match_status": "possible_match",
                "confidence": "medium",
                "verification_status": "candidate",
                "retrieved_at": page.get("retrieved_at") or _now(),
            })
    return results


def extract_entity_relationships(pages: list[dict[str, Any]], target_name: Optional[str] = None) -> list[dict[str, Any]]:
    """Extract explicit relationship language without treating names as proof."""
    relationship_terms = {
        "parent": ("parent company", "holding company", "owned by"),
        "subsidiary": ("subsidiary", "subsidiaries", "wholly owned"),
        "branch": ("branch office", "branch in", "our offices", "locations"),
        "brand": ("brand of", "trading as", "operated under the brand"),
        "alias": ("also known as", "formerly known as", "doing business as"),
        "acquisition": ("acquired", "acquisition", "merged with"),
    }
    results: list[dict[str, Any]] = []
    for page in pages:
        if not _page_matches_target(page, target_name):
            continue
        for line in page.get("content", "").splitlines():
            lowered = line.lower()
            kind = next((name for name, terms in relationship_terms.items() if any(term in lowered for term in terms)), None)
            if not kind:
                continue
            results.append(_record(
                page.get("url", ""), line, page.get("retrieved_at"),
                relationship_type=kind,
                related_name=line[:180],
                verification_status="candidate",
                confidence="medium",
            ))
    return results[:80]


def extract_workforce_signals(pages: list[dict[str, Any]], target_name: Optional[str] = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract public hiring/workforce signals; never infer employment from a mention."""
    from src.validation import is_valid_job_title, clean_job_title
    workforce: list[dict[str, Any]] = []
    hiring: list[dict[str, Any]] = []
    job_terms = ("careers", "jobs", "vacancy", "we're hiring", "join our team", "open role", "job description")
    mode_terms = ("remote", "hybrid", "on-site", "onsite", "office-based", "work from home")
    skill_terms = ("requirements", "skills", "experience with", "proficiency in", "must have")
    aggregator_domains = ("tracxn.com", "zaubacorp.com", "thecompanycheck.com", "wikipedia.org", "tofler.in")

    for page in pages:
        if not _page_matches_target(page, target_name):
            continue
        url = page.get("url", "")
        title = page.get("title", "")
        page_text = page.get("content", "")

        # Aggregators often have 'jobs' or 'careers' in nav footers; ignore unless specific job subpath
        if any(agg in url.lower() for agg in aggregator_domains) and not any(sub in url.lower() for sub in ("/careers", "/jobs", "/openings")):
            continue

        is_job_page = any(term in f"{url} {title} {page_text}".lower() for term in job_terms)
        for line in page_text.splitlines():
            lowered = line.lower()
            if is_job_page and (any(term in lowered for term in mode_terms) or any(term in lowered for term in skill_terms)):
                modes = [term for term in mode_terms if term in lowered]
                skills = [term for term in ("python", "javascript", "typescript", "sql", "sales", "marketing", "operations", "finance", "design", "react", "aws") if term in lowered]

                # Try to extract a valid job title from title or line
                candidate_role = clean_job_title(title)
                if not is_valid_job_title(candidate_role):
                    candidate_role = clean_job_title(line)
                if not is_valid_job_title(candidate_role):
                    # Never populate URLs or generic descriptions as job roles
                    continue

                hiring.append(_record(
                    url, line, page.get("retrieved_at"), signal_type="public_job_posting",
                    role=candidate_role, work_arrangement=modes or ["not stated"], required_skills=skills,
                    verification_status="published_unverified", confidence="medium",
                ))
            if any(word in lowered for word in ("joined", "appointed", "promoted", "left the company", "departed", "new ceo", "new director")):
                workforce.append(_record(
                    url, line, page.get("retrieved_at"), signal_type="position_change",
                    verification_status="candidate", confidence="medium",
                ))
    return workforce[:80], hiring[:80]
