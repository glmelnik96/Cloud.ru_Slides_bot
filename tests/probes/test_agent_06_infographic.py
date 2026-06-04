"""WS-E probe — Agent 06 (Infographic Maker, GLM-5.1 thinking-OFF)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_06_infographic_maker
from llm.roles import Role
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes._wrappers import DeckInfographics
from tests.probes.fixtures import Size, make_classification, make_content


@pytest.mark.cloudru_probe
def test_infographic_maker(size: Size, probe_report: ProbeReport) -> None:
    classification = make_classification(size)
    content = make_content(size)
    infographics, _ = run_probe(
        report=probe_report,
        agent_label="06_infographic",
        size=size,
        role=Role.INFOGRAPHIC_MAKER,
        messages=agent_06_infographic_maker.build_messages(
            classification, content,
        ),
        model_cls=DeckInfographics,
    )
    assert infographics is not None, "Infographic Maker: schema validation failed"
    # Sanity: don't invent extra slides.
    expected_max = len(classification["slides"])
    assert len(infographics.slides) <= expected_max, (
        f"Infographic Maker: produced {len(infographics.slides)} slide specs, "
        f"max expected {expected_max}"
    )
