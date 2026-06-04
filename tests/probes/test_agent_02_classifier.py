"""WS-E probe — Agent 02 (Slide Classifier, DeepSeek-V4-Pro)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_02_slide_classifier
from llm.roles import Role
from schemas.slides import DeckClassification
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes.fixtures import Size, make_brief


@pytest.mark.cloudru_probe
def test_classifier(size: Size, probe_report: ProbeReport) -> None:
    brief = make_brief(size)
    classification, _ = run_probe(
        report=probe_report,
        agent_label="02_classifier",
        size=size,
        role=Role.CLASSIFIER,
        messages=agent_02_slide_classifier.build_messages(brief),
        model_cls=DeckClassification,
    )
    assert classification is not None, "Classifier: schema validation failed"
    assert classification.slides, "Classifier: empty slides list"
    # First slide convention: title
    assert classification.slides[0].category == "title"
