"""LangChain LLM factory with provider-safe configuration."""
from __future__ import annotations

import os
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel

load_dotenv()


def get_llm(model_name: str, temperature: float = 0.0) -> BaseChatModel:
    """Create a chat model from ``provider/model``.

    Azure uses ``azure/<deployment>`` with ``AZURE_AI_ENDPOINT`` and
    ``AZURE_AI_API_KEY``. Credentials are read only from the environment.
    """
    if "/" not in model_name:
        raise ValueError(f"model_name must be 'provider/model', got: {model_name!r}")
    provider, model = model_name.split("/", 1)

    if provider in {"azure", "azure-openai"}:
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("AZURE_AI_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
        base_url = os.getenv("AZURE_AI_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_AI_DEPLOYMENT") or model
        if not api_key:
            raise ValueError("Azure AI model requested but AZURE_AI_API_KEY is not configured")
        if not base_url:
            raise ValueError("Azure AI model requested but AZURE_AI_ENDPOINT is not configured")
        if not base_url.rstrip("/").endswith("/openai/v1"):
            base_url = base_url.rstrip("/") + "/openai/v1"
        return ChatOpenAI(
            model=deployment,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            max_retries=int(os.getenv("AI_MAX_RETRIES", "2")),
            timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "60")),
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=temperature)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=temperature)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            default_headers={
                "HTTP-Referer": "https://deepresearch.ai",
                "X-Title": "DeepResearchAgent",
            },
            temperature=temperature,
        )

    raise ValueError(
        f"Unknown provider {provider!r}. Supported: anthropic, openai, google, openrouter, azure"
    )
