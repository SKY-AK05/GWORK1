"""Verification and company-intelligence helpers."""

from .company_intelligence import (
    classify_registry_outcome,
    classify_role_status,
    detect_contradictions,
    extract_business_contacts,
    extract_dated_events,
    extract_identity_candidates,
    extract_roles,
    match_company_identity,
    normalize_name,
    search_companies_house,
)
from .india import (
    INDIA_REGISTRY_SOURCES,
    build_india_verification,
    classify_india_identifier,
    classify_india_registry_outcome,
    india_name_variants,
    match_india_candidate,
    normalize_india_name,
    normalize_identifier,
)

__all__ = [
    "classify_registry_outcome",
    "classify_role_status",
    "detect_contradictions",
    "extract_business_contacts",
    "extract_dated_events",
    "extract_identity_candidates",
    "extract_roles",
    "match_company_identity",
    "normalize_name",
    "search_companies_house",
    "INDIA_REGISTRY_SOURCES",
    "build_india_verification",
    "classify_india_identifier",
    "classify_india_registry_outcome",
    "india_name_variants",
    "match_india_candidate",
    "normalize_india_name",
    "normalize_identifier",
]
