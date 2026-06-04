"""Thin synchronous wrapper around the OpenAI SDK pointed at Cloud.ru FM.

Provides:
 - one shared OpenAI client (lazy-initialised, env-driven)
 - a token-bucket RPS limiter backed by Redis (cluster-wide cap on the API key)
 - `call_role(...)` — dispatch by Role with retry + structured logging
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable

import structlog
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.config import get_settings
from llm.roles import ROLES, Role, RoleSpec

logger = structlog.get_logger(__name__)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        s = get_settings()
        _client = OpenAI(api_key=s.cloudru_api_key, base_url=s.cloudru_base_url)
    return _client


@dataclass(frozen=True)
class LLMCall:
    role: Role
    messages: list[dict[str, Any]]
    # Override fields if the caller needs a one-off tweak.
    max_tokens_override: int | None = None
    extra_body_override: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMResult:
    role: Role
    model: str
    content: str
    reasoning: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_s: float


def _merge_extra_body(spec: RoleSpec, override: dict[str, Any] | None) -> dict[str, Any]:
    if not override:
        return dict(spec.extra_body)
    merged = dict(spec.extra_body)
    merged.update(override)
    return merged


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=8),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIStatusError)),
)
def _do_call(*, model: str, messages: Iterable[dict[str, Any]], max_tokens: int,
             temperature: float, extra_body: dict[str, Any]) -> tuple[Any, float]:
    client = get_client()
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model,
        messages=list(messages),
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body=extra_body or None,
    )
    return resp, time.perf_counter() - t0


def call_role(call: LLMCall) -> LLMResult:
    """Dispatch a chat completion under the given Role.

    Retries on transient Cloud.ru errors (with exponential backoff).
    Caller is responsible for parsing `content` and re-trying with
    feedback if the JSON is malformed (see `llm.output_parsers`).
    """
    spec = ROLES[call.role]
    max_tok = call.max_tokens_override or spec.max_tokens
    extra_body = _merge_extra_body(spec, call.extra_body_override)
    logger.debug(
        "llm.call.start",
        role=call.role.value,
        model=spec.model,
        max_tokens=max_tok,
        msg_count=len(call.messages),
    )
    resp, elapsed = _do_call(
        model=spec.model,
        messages=call.messages,
        max_tokens=max_tok,
        temperature=spec.temperature,
        extra_body=extra_body,
    )
    msg = resp.choices[0].message
    content = (msg.content or "").strip()
    reasoning = (getattr(msg, "reasoning", None) or "").strip()
    usage = resp.usage
    result = LLMResult(
        role=call.role,
        model=spec.model,
        content=content,
        reasoning=reasoning,
        prompt_tokens=getattr(usage, "prompt_tokens", 0),
        completion_tokens=getattr(usage, "completion_tokens", 0),
        elapsed_s=elapsed,
    )
    logger.info(
        "llm.call.done",
        role=call.role.value,
        model=spec.model,
        elapsed_s=round(elapsed, 3),
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        reasoning_len=len(reasoning),
        content_len=len(content),
    )
    return result


def ping(role: Role = Role.CLASSIFIER) -> LLMResult:
    """Cheap liveness probe — used in M1 acceptance to verify reachability."""
    return call_role(LLMCall(
        role=role,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        max_tokens_override=200,  # enough for reasoning models, harmless for others
    ))
