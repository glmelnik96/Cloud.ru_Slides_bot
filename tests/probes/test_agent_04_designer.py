"""WS-E probe — Agent 04 (Layout Designer, DeepSeek-V4-Pro)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_04_layout_designer
from llm.roles import Role
from schemas.slides import LayoutPlan
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes.fixtures import Size, make_classification


@pytest.mark.cloudru_probe
def test_designer(size: Size, probe_report: ProbeReport) -> None:
    classification = make_classification(size)
    layouts, _ = run_probe(
        report=probe_report,
        agent_label="04_designer",
        size=size,
        role=Role.DESIGNER,
        messages=agent_04_layout_designer.build_messages(classification),
        model_cls=LayoutPlan,
    )
    assert layouts is not None, "Designer: schema validation failed"
    assert layouts.slides, "Designer: empty slides list"
    expected_n = len(classification["slides"])
    assert len(layouts.slides) == expected_n, (
        f"Designer: emitted {len(layouts.slides)} layouts, expected {expected_n}"
    )
    # Anti-monotony lite: no donor should occupy 3+ in a row — except
    # layout_idx=0 ("native render — donor not applicable"), which is the
    # canonical value for chart/table/flow/image natives and CAN legitimately
    # repeat (e.g. chart→table→flow stretch in big fixture).
    seq = [s.donor for s in layouts.slides if s.donor != 0]
    triple = any(seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2))
    assert not triple, f"Designer: 3-in-a-row donor detected: {seq}"
