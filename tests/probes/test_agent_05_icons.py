"""WS-E probe — Agent 05 (Icon Picker, GLM-5.1 thinking-OFF)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_05_icon_picker
from llm.roles import Role
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes._wrappers import DeckIcons
from tests.probes.fixtures import (
    Size,
    make_classification,
    make_content,
    make_icon_library,
)


@pytest.mark.cloudru_probe
def test_icon_picker(size: Size, probe_report: ProbeReport) -> None:
    classification = make_classification(size)
    content = make_content(size)
    library = make_icon_library()
    icons, _ = run_probe(
        report=probe_report,
        agent_label="05_icons",
        size=size,
        role=Role.ICON_PICKER,
        messages=agent_05_icon_picker.build_messages(
            classification, content, library,
        ),
        model_cls=DeckIcons,
    )
    assert icons is not None, "Icon Picker: schema validation failed"
    # Title slides should produce empty icon_assignments per prompt rule.
    by_num = {s.slide_num: s for s in icons.slides}
    if 1 in by_num:
        assert by_num[1].icon_assignments == [], \
            "Icon Picker: title slide should have empty icon_assignments"
