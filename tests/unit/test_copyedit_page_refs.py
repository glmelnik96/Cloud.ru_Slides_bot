"""FIX9: deterministic strip of source-brief page-reference citations.

The Горбачевский brief carries inline source-page citations like "(стр. 3)"
and "(стр. 5, 10)". These survive copyediting into card bodies (deck3 s14),
where they read as stray noise. Strip them deterministically post-copyedit,
mirroring the emoji strip, so we don't depend on the LLM remembering to.
"""
from __future__ import annotations

import pytest

from graph.nodes.agents import _strip_page_refs, _strip_page_refs_from_content


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Внедрение ИИ-агентов (стр. 3)", "Внедрение ИИ-агентов"),
        ("Результаты пилота (стр. 5, 10) подтверждены", "Результаты пилота подтверждены"),
        ("Метрика (стр.7) выросла", "Метрика выросла"),
        ("Источник (стр 12)", "Источник"),
        ("Диапазон (стр. 5-10)", "Диапазон"),
        # No page-ref → unchanged.
        ("Обычный текст без ссылок", "Обычный текст без ссылок"),
        # Parenthesised non-page content is preserved.
        ("Рост выручки (на 30%)", "Рост выручки (на 30%)"),
    ],
)
def test_strip_page_refs(raw: str, expected: str) -> None:
    assert _strip_page_refs(raw) == expected


def test_strip_page_refs_from_content_counts_and_mutates() -> None:
    dump = {
        "slides": [
            {
                "placeholder_assignments": [
                    {"content": "Пункт один (стр. 3)"},
                    {"content": "Пункт два без ссылки"},
                    {"content": "Пункт три (стр. 5, 10)"},
                    {"content": 42},  # non-str ignored
                ]
            }
        ]
    }
    changed = _strip_page_refs_from_content(dump)
    assert changed == 2
    phs = dump["slides"][0]["placeholder_assignments"]
    assert phs[0]["content"] == "Пункт один"
    assert phs[1]["content"] == "Пункт два без ссылки"
    assert phs[2]["content"] == "Пункт три"
