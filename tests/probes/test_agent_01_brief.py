"""WS-E probe — Agent 01 (Brief Reader, Kimi-K2.6 vision).

Per ``prompt_adaptation.md``, original Anthropic prompts must be
re-engineered for each Cloud.ru FM model. This probe asserts the
re-engineered Brief Reader prompt round-trips a synthetic parsed deck
into a schema-valid ``Brief`` across all 3 deck sizes.

A 1×1 transparent PNG is injected to satisfy Kimi's vision-gate.
"""
from __future__ import annotations

import pytest

from llm.prompts import agent_01_brief_reader
from llm.roles import Role
from schemas.slides import Brief
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes.fixtures import PIXEL_PNG_DATA_URL, Size, make_parsed_deck


@pytest.mark.cloudru_probe
def test_brief_reader(size: Size, probe_report: ProbeReport) -> None:
    parsed_deck = make_parsed_deck(size)
    messages, images = agent_01_brief_reader.build_messages(
        parsed_deck, images=[PIXEL_PNG_DATA_URL],
    )
    brief, _ = run_probe(
        report=probe_report,
        agent_label="01_brief",
        size=size,
        role=Role.BRIEF_PARSER,
        messages=messages,
        model_cls=Brief,
        images=images,
    )
    assert brief is not None, "Brief Reader: schema validation failed"
    assert brief.slide_count == parsed_deck["slide_count"]
    assert brief.slides, "Brief Reader: empty slides list"
