"""Probe runner — wraps `call_and_parse` with retry-counting metrics.

The orchestrator helper hides the attempt count behind a tuple return.
For probe reporting we need to know whether the first attempt parsed or
the retry-with-feedback was needed. This module re-implements the same
retry loop so we can record both outcomes.

Keep behaviour 1:1 with ``llm.output_parsers.call_and_parse``: same
prompt, same retry feedback string, same exception flow.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from llm.client import LLMCall, LLMResult, call_role
from llm.output_parsers import parse_json_or_raise
from llm.roles import ROLES, Role
from tests.probes._report import ProbeReport, ProbeRow

_ARTIFACTS_DIR = Path(__file__).parent / "_artifacts"

T = TypeVar("T", bound=BaseModel)


def run_probe(
    *,
    report: ProbeReport,
    agent_label: str,
    size: str,
    role: Role,
    messages: list[dict[str, Any]],
    model_cls: type[T],
    images: list[Any] | None = None,
    max_retries: int = 1,
) -> tuple[T | None, LLMResult]:
    """Run one probe call. Records a row into ``report`` then returns the
    parsed model (or None on failure) and the final LLMResult.

    On schema failure after retries the row is recorded with schema_ok=False
    and the test caller asserts that result.
    """
    msgs = [dict(m) for m in messages]
    started = time.monotonic()
    retry_used = False
    last_result: LLMResult | None = None
    last_err: Exception | None = None
    parsed: T | None = None
    for attempt in range(max_retries + 1):
        result = call_role(LLMCall(role=role, messages=msgs, images=list(images or [])))
        last_result = result
        try:
            data = parse_json_or_raise(result.content)
            parsed = model_cls.model_validate(data)
            break
        except (ValueError, ValidationError) as e:
            last_err = e
            if attempt >= max_retries:
                break
            retry_used = True
            feedback = (
                "Предыдущий ответ невалиден по схеме. Ошибка: "
                f"{type(e).__name__}: {str(e)[:500]}.\n"
                "Верни ТОЛЬКО валидный JSON по схеме из system-сообщения. "
                "Без markdown-ограждений, без пояснений."
            )
            msgs.append({"role": "assistant", "content": result.content})
            msgs.append({"role": "user", "content": feedback})

    assert last_result is not None
    elapsed = time.monotonic() - started
    schema_ok = parsed is not None
    head = (last_result.content or "")[:120].replace("\n", " ")
    err = "" if schema_ok else f"{type(last_err).__name__}: {str(last_err)[:200]}"

    # Always persist raw final content for triage. Failures get a .err sidecar.
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = _ARTIFACTS_DIR / f"{agent_label}_{size}.txt"
    raw_path.write_text(last_result.content or "", encoding="utf-8")
    if not schema_ok and last_err is not None:
        err_path = _ARTIFACTS_DIR / f"{agent_label}_{size}.err"
        err_path.write_text(
            f"{type(last_err).__name__}: {last_err}\n", encoding="utf-8"
        )
    report.record(ProbeRow(
        agent=agent_label,
        size=size,
        model=ROLES[role].model,
        schema_ok=schema_ok,
        retry_used=retry_used,
        elapsed_s=elapsed,
        prompt_tokens=last_result.prompt_tokens,
        completion_tokens=last_result.completion_tokens,
        content_head=head,
        error=err,
    ))
    return parsed, last_result
