"""WS-E probe — Agent 07 (Copy Editor, GLM-5.1 thinking-OFF)."""
from __future__ import annotations

import pytest

from llm.prompts import agent_07_copy_editor
from llm.roles import Role
from tests.probes._report import ProbeReport
from tests.probes._runner import run_probe
from tests.probes._wrappers import DeckContent
from tests.probes.fixtures import Size, make_content


@pytest.mark.cloudru_probe
def test_copy_editor(size: Size, probe_report: ProbeReport) -> None:
    content = make_content(size)
    edited, _ = run_probe(
        report=probe_report,
        agent_label="07_copyedit",
        size=size,
        role=Role.COPY_EDITOR,
        messages=agent_07_copy_editor.build_messages(content),
        model_cls=DeckContent,
    )
    assert edited is not None, "Copy Editor: schema validation failed"
    expected = len(content["slides"])
    assert len(edited.slides) == expected, (
        f"Copy Editor: returned {len(edited.slides)} slides, expected {expected}"
    )
    # At least one of the fixture's ' -- ' substrings should be replaced with em-dash
    # somewhere in the deck (size=small has 1 ' -- ' in slide 3; big has more).
    em_dash = "\u2014"
    any_em = any(
        em_dash in p.content
        for s in edited.slides for p in s.placeholder_assignments
    )
    assert any_em, "Copy Editor: no em-dashes produced (Russian typography rule)"
