"""T1.2: autofix routing — categorize issues, skip when COPY_EDITOR can't help.

Background: 2026-06-04 live run had 11 blockers + 13 warnings; autofix
re-ran COPY_EDITOR for all of them and ended up with 11 blockers + 13
warnings (no improvement, regression on warnings). 8/11 blockers were
text_replaced (placeholder leak — build bug) and 13 warnings were aesthetic
(needed visual agent, not text editor). The categorization here prevents
that waste.
"""
from __future__ import annotations

import pytest

from graph.nodes.agents import (
    _categorize_issue,
    autofix_can_help,
    issue_breakdown,
)


@pytest.mark.parametrize("line, expected", [
    # Real live-run blockers (Russian phrasing preserved).
    ("slide 4: slide[4].body: текст 337 chars > max 200 (overflow 1.69x)",
     "text_overflow"),
    ("visual slide 7: text_replaced — placeholder «Подзаголовок» вместо реальных",
     "text_replaced"),
    ("visual slide 7: semantics_ok — Контент не соответствует теме",
     "semantics"),
    ("visual slide 5: hierarchy — Три блока текста равного веса", "aesthetic"),
    ("visual slide 2: philosophy — нет бренд-акцентов", "aesthetic"),
    ("visual slide 4: function — Стена текста не сканируется", "aesthetic"),
    ("AUTO STRATEGY 3 — overflow 152>120, размер уменьшен", "text_overflow"),
    ("some unknown warning", "other"),
])
def test_categorize_issue(line: str, expected: str) -> None:
    assert _categorize_issue(line) == expected


def _make_arts(blockers: list[str], warnings: list[str] | None = None) -> dict:
    return {"verifier_verdict": {
        "blockers": blockers,
        "warnings": warnings or [],
    }}


def test_issue_breakdown_counts_by_category() -> None:
    arts = _make_arts(
        blockers=[
            "slide[4].body: текст 337 chars > max 200",      # text_overflow
            "slide 7: text_replaced — placeholder",          # text_replaced
            "slide 7: semantics_ok — не соответствует",      # semantics
        ],
        warnings=[
            "slide 5: hierarchy",       # aesthetic
            "slide 2: philosophy",      # aesthetic
        ],
    )
    b = issue_breakdown(arts)
    assert b["text_overflow"] == 1
    assert b["text_replaced"] == 1
    assert b["semantics"] == 1
    assert b["aesthetic"] == 2
    assert b["other"] == 0


def test_autofix_can_help_when_text_overflow_present() -> None:
    arts = _make_arts(blockers=["chars > max 200 overflow"])
    assert autofix_can_help(arts) is True


def test_autofix_can_help_when_only_semantics() -> None:
    arts = _make_arts(blockers=["slide 4: semantics_ok — не соответствует"])
    assert autofix_can_help(arts) is True


def test_autofix_skips_when_only_placeholder_leak() -> None:
    """Live-run scenario: COPY_EDITOR can't fix build/donor bugs."""
    arts = _make_arts(blockers=[
        "slide 7: text_replaced — placeholder",
        "slide 9: text_replaced — placeholder",
        "slide 11: text_replaced — placeholder",
    ])
    assert autofix_can_help(arts) is False


def test_autofix_skips_when_only_aesthetic_warnings() -> None:
    arts = _make_arts(blockers=[], warnings=[
        "slide 2: detail — нет бренд-акцентов",
        "slide 5: hierarchy — три блока равного веса",
        "slide 4: function — стена текста",
    ])
    assert autofix_can_help(arts) is False


def test_autofix_skips_when_no_issues() -> None:
    arts = _make_arts(blockers=[], warnings=[])
    assert autofix_can_help(arts) is False


def test_issue_breakdown_handles_dict_items() -> None:
    """Verifier may emit blockers as dicts with .msg / .text fields."""
    arts = {"verifier_verdict": {
        "blockers": [
            {"msg": "slide 4: chars > max 200 overflow"},
            {"text": "slide 7: text_replaced"},
        ],
        "warnings": [],
    }}
    b = issue_breakdown(arts)
    assert b["text_overflow"] == 1
    assert b["text_replaced"] == 1
