"""D7: deterministic wall-of-text splitter.

Live run 2026-06-05 (run1.slide5) had a 480-char single-paragraph body
slot. These tests pin the splitter behaviour so a long body paragraph
becomes multiple bullets at sentence boundaries.
"""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from bullet_splitter import (  # noqa: E402 — path injected by skill_bridge
    MAX_BULLET_CHARS,
    _is_body_slot,
    split_long_bullet,
    split_slot_if_body,
)


def test_short_text_unchanged() -> None:
    text = "Один короткий буллет — ничего трогать не нужно."
    assert split_long_bullet(text) == text


def test_already_split_text_unchanged() -> None:
    text = "Первый буллет." + "\n" + "Второй буллет."
    assert split_long_bullet(text) == text


def test_long_paragraph_splits_at_sentence_breaks() -> None:
    """Russian sentence breakers . ? ! all work."""
    long_text = (
        "У нас есть кластер с резервированием по нескольким зонам доступности. "
        "Покрытие — все ключевые регионы, инфраструктура работает 24/7. "
        "Дополнительно мы поддерживаем горячую миграцию между нодами без даунтайма. "
        "В случае аварии данные восстанавливаются за считанные минуты."
    )
    assert len(long_text) > MAX_BULLET_CHARS
    out = split_long_bullet(long_text)
    parts = out.split("\n")
    assert len(parts) >= 2, f"expected ≥2 bullets, got {len(parts)}: {parts}"
    # Every bullet must respect the cap.
    assert all(len(p) <= MAX_BULLET_CHARS for p in parts), parts


def test_no_sentence_boundary_kept_intact() -> None:
    """If we can't find a safe split point, leave it alone — better than mangling."""
    weird = "x" * 400
    assert split_long_bullet(weird) == weird


def test_slot_filter_skips_title() -> None:
    """Title slots never get split — they're single-line typographic."""
    long_text = (
        "Очень длинный заголовок без предложений. С двумя точками. И ещё двумя. "
        "А вот и третья."
    ) * 3
    out = split_slot_if_body("title", long_text)
    assert out == long_text


def test_slot_filter_processes_body() -> None:
    long_text = (
        "У нас есть кластер с резервированием. " * 10
    )
    out = split_slot_if_body("body", long_text)
    assert "\n" in out


def test_is_body_slot_substring_matches() -> None:
    """col1_body, col2_body, body_left, lead_body — all body-ish."""
    assert _is_body_slot("col1_body")
    assert _is_body_slot("col2_body")
    assert _is_body_slot("body_left")
    assert _is_body_slot("lead_body")
    assert _is_body_slot("content")
    assert not _is_body_slot("title")
    assert not _is_body_slot("subtitle")
    assert not _is_body_slot("caption")
