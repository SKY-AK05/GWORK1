import os

import pytest

from src.browser.authorized import AuthorizedBrowserResearch, BrowserConsentRequired
from src.llm.factory import get_llm
from src.tools.registry import validate_plan_tools


def test_azure_provider_requires_local_configuration(monkeypatch):
    monkeypatch.delenv("AZURE_AI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="AZURE_AI_API_KEY"):
        get_llm("azure/gpt-5.4-mini")


def test_azure_provider_uses_endpoint_and_deployment(monkeypatch):
    monkeypatch.setenv("AZURE_AI_API_KEY", "test-only-not-a-real-secret")
    monkeypatch.setenv("AZURE_AI_ENDPOINT", "https://example.ai.azure.com")
    monkeypatch.setenv("AZURE_AI_DEPLOYMENT", "gpt-5.4-mini")
    llm = get_llm("azure/gpt-5.4-mini")
    assert llm.model_name == "gpt-5.4-mini"
    assert llm.openai_api_base.endswith("/openai/v1")


def test_browser_requires_explicit_consent(monkeypatch):
    monkeypatch.delenv("BROWSER_PERSISTENT_SESSION", raising=False)
    with pytest.raises(BrowserConsentRequired):
        AuthorizedBrowserResearch(consent=False)


def test_persistent_browser_requires_configuration_consent(monkeypatch):
    monkeypatch.setenv("BROWSER_PERSISTENT_SESSION", "false")
    with pytest.raises(BrowserConsentRequired):
        AuthorizedBrowserResearch(consent=True, persistent=True)


def test_model_cannot_execute_unregistered_tool_category():
    result = validate_plan_tools({"items": [{"question": "x", "tool_category": "shell"}]})
    assert result["items"] == []
    assert result["rejected"][0]["reason"] == "unregistered category"
