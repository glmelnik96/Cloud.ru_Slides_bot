"""WS-E probe — Agent 03 (Content Distributor, GLM-5.1 thinking-OFF)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_03_content_distributor
from llm.roles import Role
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes._wrappers import DeckContent
from tests.probes.fixtures import (
    Size,
    make_brief,
    make_classification,
    make_layouts,
    make_slot_specs,
)


@pytest.mark.cloudru_probe
def test_distributor(size: Size, probe_report: ProbeReport) -> None:
    brief = make_brief(size)
    classification = make_classification(size)
    layouts = make_layouts(size)
    slot_specs = make_slot_specs(size)
    content, _ = run_probe(
        report=probe_report,
        agent_label="03_distributor",
        size=size,
        role=Role.DISTRIBUTOR,
        messages=agent_03_content_distributor.build_messages(
            brief, classification, layouts, slot_specs,
        ),
        model_cls=DeckContent,
    )
    assert content is not None, "Distributor: schema validation failed"
    assert content.slides, "Distributor: empty slides list"
    # Title slide must carry a non-empty title placeholder.
    first = content.slides[0]
    assert any(p.content.strip() for p in first.placeholder_assignments), \
        "Distributor: title slide placeholders all empty"
