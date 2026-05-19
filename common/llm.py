"""
LLM abstraction using LiteLLM.
Swap models by changing LLM_MODEL (and optionally LLM_API_BASE) in .env.

Supported backends (examples):
  claude-sonnet-4-20250514          → Anthropic
  openai/gpt-4o                     → OpenAI
  ollama/llama3                     → local Ollama  (set LLM_API_BASE=http://localhost:11434)
  openai/mistral-7b-instruct        → vLLM          (set LLM_API_BASE=http://localhost:8000/v1)
  mistral/mistral-large-latest      → Mistral API
"""
from __future__ import annotations

import time
from typing import Any

import litellm
import structlog

from common.config import settings

log = structlog.get_logger()

# Silence litellm's verbose logging by default
litellm.set_verbose = False


def _build_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": settings.llm_model}
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    if settings.llm_api_key:
        kwargs["api_key"] = settings.llm_api_key
    return kwargs


def chat(
    messages: list[dict[str, str]],
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
) -> litellm.ModelResponse:
    """
    Single chat completion call.
    Returns the raw LiteLLM ModelResponse so callers can inspect tool calls, etc.
    """
    kwargs = _build_kwargs()
    kwargs["messages"] = messages
    kwargs["max_tokens"] = max_tokens
    if tools:
        kwargs["tools"] = tools

    log.debug("llm_call", model=settings.llm_model, n_messages=len(messages))
    for attempt in range(4):
        try:
            response = litellm.completion(**kwargs)
            log.debug("llm_response", usage=response.usage)
            return response
        except litellm.RateLimitError as e:
            if attempt == 3:
                raise
            wait = 2 ** (attempt + 1) * 15  # 30s, 60s, 120s
            log.warning("llm_rate_limit", wait_seconds=wait, attempt=attempt + 1)
            time.sleep(wait)


def extract_text(response: litellm.ModelResponse) -> str:
    """Pull the text content from the first choice."""
    return response.choices[0].message.content or ""


def extract_tool_calls(response: litellm.ModelResponse) -> list[dict]:
    """Return tool call objects from the response, or empty list."""
    message = response.choices[0].message
    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return []
    return message.tool_calls
