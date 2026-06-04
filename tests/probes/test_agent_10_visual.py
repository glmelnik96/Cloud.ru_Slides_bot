"""WS-E probe — Agent 10 (Visual Verifier, Kimi-K2.6 vision).

Real PNGs from rendered decks land in chunk C. For now we feed the
1×1 transparent PNG per slide so the vision-gate is satisfied. The
Visual Verifier will (correctly) say NEEDS_REWORK because the placeholder
PNGs have no content — we only assert the *schema* is valid.
"""
from __future__ import annotations

import pytest

from llm.prompts import agent_10_visual_verifier
from llm.roles import Role
from schemas.slides import VisualVerdict
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes.fixtures import PIXEL_PNG_DATA_URL, Size, make_plan


@pytest.mark.cloudru_probe
def test_visual_verifier(size: Size, probe_report: ProbeReport) -> None:
    plan = make_plan(size)
    n = len(plan["slides"])
    images = [PIXEL_PNG_DATA_URL] * n
    messages, imgs = agent_10_visual_verifier.build_messages(plan, images)
    verdict, _ = run_probe(
        report=probe_report,
        agent_label="10_visual",
        size=size,
        role=Role.VISUAL_VERIFIER,
        messages=messages,
        model_cls=VisualVerdict,
        images=imgs,
    )
    assert verdict is not None, "Visual Verifier: schema validation failed"
    # Placeholder PNGs are blank — verdict will be NEEDS_REWORK; that's expected.
    # We only assert the schema is valid + verdict field is one of the literals.
    assert verdict.llm_verdict in ("READY", "NEEDS_REWORK")
