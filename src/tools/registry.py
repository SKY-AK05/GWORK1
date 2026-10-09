"""Permitted research-tool registry used to validate model recommendations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    purpose: str
    credential: str | None
    enabled_by_default: bool = True
    limitations: str = ""


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "web_search": ToolSpec("web_search", "discovery", "Search public web indexes.", None),
    "crawl4ai": ToolSpec("crawl4ai", "crawling", "Fetch accessible public pages.", None),
    "companies_house": ToolSpec("companies_house", "registry", "Query the official UK company registry.", "COMPANIES_HOUSE_API_KEY", limitations="UK only; unavailable without a key."),
    "india_registry": ToolSpec("india_registry", "registry", "Use supported public/authorized India registry sources.", None, limitations="CAPTCHA/OTP and restricted portals are not automated."),
    "browser_public": ToolSpec("browser_public", "browser", "Read public pages in an isolated browser context.", None),
    "browser_authorized": ToolSpec("browser_authorized", "browser", "Read pages after explicit user consent and user-managed login.", None, enabled_by_default=False, limitations="No passwords, cookies, private messages, CAPTCHA, MFA, OTP, or paywall bypass."),
}


def permitted_tool(name: str, *, enabled: bool = True) -> ToolSpec:
    if name not in TOOL_REGISTRY:
        raise ValueError(f"Model proposed an unregistered tool: {name}")
    spec = TOOL_REGISTRY[name]
    if not enabled or not spec.enabled_by_default:
        raise PermissionError(f"Tool is not enabled for this run: {name}")
    return spec


def validate_plan_tools(plan: dict[str, Any]) -> dict[str, Any]:
    """Return a plan with invalid tool categories rejected, never executed."""
    allowed_categories = {spec.category for spec in TOOL_REGISTRY.values() if spec.enabled_by_default}
    items = []
    rejected = []
    for item in plan.get("items", []):
        category = str(item.get("tool_category", ""))
        if category not in allowed_categories:
            rejected.append({"question": item.get("question", ""), "tool_category": category, "reason": "unregistered category"})
            continue
        items.append(item)
    return {"items": items, "rejected": rejected, "rationale": plan.get("rationale", "")}
