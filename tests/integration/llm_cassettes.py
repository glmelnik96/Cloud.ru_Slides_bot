"""Cassette helpers for offline LLM-node tests.

Each cassette is the raw model response captured by the WS-E probe runner
into ``tests/probes/_artifacts/{label}_{size}.txt``. We stub
``llm.output_parsers.call_role`` so the agent nodes execute end-to-end
(``build_messages`` → JSON parse → Pydantic validate → artefact patch)
without hitting Cloud.ru.

Why patch in ``llm.output_parsers`` and not ``llm.client``? The parser
binds ``call_role`` at import time (``from llm.client import call_role``),
so the agent-node path goes through that local reference.
"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from llm.client import LLMCall, LLMResult
from llm.roles import ROLES, Role

_ARTIFACTS = Path(__file__).resolve().parents[1] / "probes" / "_artifacts"


def load_cassette(label: str, size: str) -> str:
    """Read the captured raw model output for ``{label}_{size}``."""
    p = _ARTIFACTS / f"{label}_{size}.txt"
    if not p.is_file():
        raise FileNotFoundError(f"cassette missing: {p}")
    return p.read_text(encoding="utf-8")


def make_result(role: Role, content: str) -> LLMResult:
    """Wrap canned content into the ``LLMResult`` shape the parser expects."""
    return LLMResult(
        role=role,
        model=ROLES[role].model,
        content=content,
        reasoning="",
        prompt_tokens=0,
        completion_tokens=0,
        elapsed_s=0.0,
    )


class CassetteCallRole:
    """Drop-in replacement for ``llm.output_parsers.call_role``.

    Constructed with a ``{Role: cassette_text}`` mapping. Each invocation
    returns the canned response for the requested role. Useful for chaining
    multiple agent nodes in a single test, where each node may use a
    different role.
    """

    def __init__(self, mapping: Mapping[Role, str]) -> None:
        self._mapping = dict(mapping)
        self.calls: list[LLMCall] = []  # spy — tests can assert what was sent

    def __call__(self, call: LLMCall) -> LLMResult:
        self.calls.append(call)
        if call.role not in self._mapping:
            raise RuntimeError(
                f"CassetteCallRole: no cassette registered for {call.role.value}"
            )
        return make_result(call.role, self._mapping[call.role])
