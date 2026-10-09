"""LangChain LLM factory — replaces the custom ModelManager."""

from __future__ import annotations

import os
from langchain_core.language_models.chat_models import BaseChatModel


def get_llm(model_name: str, temperature: float = 0.0) -> BaseChatModel:
    """Create a LangChain chat model from a 'provider/model' string.

    Supported formats:
      anthropic/claude-sonnet-4-5
      openai/gpt-4o
      google/gemini-2.5-flash
      openrouter/<any-openrouter-model-id>
    """
    if "/" not in model_name:
        raise ValueError(
            f"model_name must be 'provider/model', got: {model_name!r}"
        )

    provider, model = model_name.split("/", 1)

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
        f"Unknown provider {provider!r}. Supported: anthropic, openai, google, openrouter"
    )
