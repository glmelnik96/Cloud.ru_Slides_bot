"""Parse LLM JSON output into a Pydantic model with 1 retry on schema error.

Cloud.ru FM doesn't support `response_format: json_schema` (per
`<project>/memory/cloudru_fm_api.md`). The contract is plain prompt
+ Pydantic validation + 1 retry-with-feedback, empirically 4/4 schema_ok
on GLM-OFF and DeepSeek.
"""
from __future__ import annotations

import json
import re
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from llm.client import LLMCall, LLMResult, call_role
from llm.roles import Role

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """Some models still emit ```json fences despite instructions — peel them."""
    return _FENCE_RE.sub("", text).strip()


def _find_first_json_object(text: str) -> str | None:
    """Locate the first balanced { ... } substring. Returns None if not found."""
    text = _strip_fences(text)
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start:i + 1]
    return None


def parse_json_or_raise(content: str) -> dict[str, Any]:
    """Best-effort JSON extraction. Raises ValueError with a short reason."""
    blob = _find_first_json_object(content) or _strip_fences(content)
    if not blob:
        raise ValueError("no JSON object found in model output")
    try:
        return json.loads(blob)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSONDecodeError: {e.msg} at pos {e.pos}") from e


def call_and_parse(
    role: Role,
    messages: list[dict[str, Any]],
    model_cls: type[T],
    *,
    images: list[Any] | None = None,
    max_retries: int = 1,
) -> tuple[T, LLMResult]:
    """Call the role, parse content as JSON, validate against ``model_cls``.

    On validation/parse error, append a feedback user message describing the
    issue and retry once (or ``max_retries`` times). If still failing, raises
    the last error so the caller can decide HALT/skip.

    Returns:
        (model_instance, raw LLMResult of the final attempt).
    """
    msgs = [dict(m) for m in messages]
    last_err: Exception | None = None
    last_result: LLMResult | None = None
    for attempt in range(max_retries + 1):
        result = call_role(LLMCall(role=role, messages=msgs, images=list(images or [])))
        last_result = result
        try:
            data = parse_json_or_raise(result.content)
            model = model_cls.model_validate(data)
            if attempt > 0:
                logger.info("llm.parse.retry_ok", role=role.value, attempt=attempt)
            return model, result
        except (ValueError, ValidationError) as e:
            last_err = e
            logger.warning(
                "llm.parse.fail",
                role=role.value,
                attempt=attempt,
                error=str(e)[:300],
                content_head=result.content[:200],
            )
            if attempt >= max_retries:
                break
            # Feedback turn — append assistant's bad output + user correction.
            feedback = (
                "Предыдущий ответ невалиден по схеме. Ошибка: "
                f"{type(e).__name__}: {str(e)[:500]}.\n"
                "Верни ТОЛЬКО валидный JSON по схеме из system-сообщения. "
                "Без markdown-ограждений, без пояснений."
            )
            msgs.append({"role": "assistant", "content": result.content})
            msgs.append({"role": "user", "content": feedback})

    assert last_err is not None and last_result is not None
    raise last_err
