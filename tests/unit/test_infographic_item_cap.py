"""Task 5: process/flow infographic item cap.

Root cause (live): recovered body lines (11) became 10 process/flow
cards, but the horizontal step layout only fits ~8 cards inside the
safe-area — the bottom/right cards clipped off the slide because there
was no item cap.

Fix: cap the cards fed to a `process`/`flow` native infographic to the
layout capacity (8). Overflow is NEVER silently dropped — the text of
all overflow cards is merged into the last shown card so every word is
preserved. The cap runs at the feed point (before the renderer), so the
renderer always receives ≤ cap cards.

These tests pin the deterministic cap+merge helper.
"""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from infographic_renderer import (  # noqa: E402  (path injected by skill_bridge)
    _PROCESS_MAX_ITEMS,
    cap_process_items,
)

_EMU = 9525  # 1 px


def _card(idx: int, text: str) -> dict:
    """A process card (block) carrying a label."""
    return {
        "type": "rounded_rect",
        "left_emu": (30 + idx * 100) * _EMU,
        "top_emu": 300 * _EMU,
        "width_emu": 90 * _EMU,
        "height_emu": 120 * _EMU,
        "fill_color": "#F2F2F2",
        "stroke_color": "none",
        "stroke_width_pt": 0.0,
        "text": text,
        "font": "SB Sans Display",
        "font_size_pt": 12,
        "font_color": "#222222",
    }


def _arrow(idx: int) -> dict:
    """A connector arrow between card idx and idx+1."""
    return {
        "type": "arrow",
        "left_emu": (120 + idx * 100) * _EMU,
        "top_emu": 350 * _EMU,
        "width_emu": 10 * _EMU,
        "height_emu": 10 * _EMU,
        "fill_color": "#222222",
        "stroke_color": "#222222",
        "stroke_width_pt": 1.0,
        "text": "",
    }


def _interleaved(n_cards: int) -> list[dict]:
    """N cards + (N-1) arrows, in render order: card, arrow, card, ..."""
    shapes: list[dict] = []
    for i in range(n_cards):
        shapes.append(_card(i, f"Шаг {i + 1}"))
        if i < n_cards - 1:
            shapes.append(_arrow(i))
    return shapes


def _card_texts(shapes: list[dict]) -> list[str]:
    return [
        s["text"] for s in shapes
        if s.get("type") in ("rounded_rect", "rectangle", "circle")
    ]


def test_cap_over_capacity_merges_overflow_no_drop() -> None:
    """(a) >cap cards → capped to cap, with NO card text dropped: the
    overflow card labels are merged into the last shown card."""
    n = _PROCESS_MAX_ITEMS + 3  # 11 cards (the live failure was 10-11)
    shapes = _interleaved(n)
    original_words = [f"Шаг {i + 1}" for i in range(n)]

    capped = cap_process_items("process", shapes)

    card_texts = _card_texts(capped)
    # Exactly cap cards survive.
    assert len(card_texts) == _PROCESS_MAX_ITEMS
    # The first cap-1 cards are unchanged.
    for i in range(_PROCESS_MAX_ITEMS - 1):
        assert card_texts[i] == original_words[i]
    # Every overflow word is preserved in the last shown card.
    last = card_texts[_PROCESS_MAX_ITEMS - 1]
    for word in original_words[_PROCESS_MAX_ITEMS - 1:]:
        assert word in last, f"{word!r} was clipped (not in merged last card)"
    # No orphan connector arrows beyond the kept cards.
    arrows = [s for s in capped if s.get("type") == "arrow"]
    assert len(arrows) <= _PROCESS_MAX_ITEMS - 1


def test_cap_at_or_under_capacity_unchanged() -> None:
    """(b) ≤cap cards → list returned unchanged (same objects, same order)."""
    shapes = _interleaved(_PROCESS_MAX_ITEMS)  # exactly cap cards
    snapshot = [dict(s) for s in shapes]

    capped = cap_process_items("process", shapes)

    assert capped == snapshot
    assert _card_texts(capped) == [f"Шаг {i + 1}" for i in range(_PROCESS_MAX_ITEMS)]


def test_cap_only_applies_to_process_and_flow() -> None:
    """A comparison/matrix layout is not a horizontal step row — leave it
    untouched even if it has many shapes."""
    shapes = _interleaved(_PROCESS_MAX_ITEMS + 4)
    snapshot = [dict(s) for s in shapes]
    assert cap_process_items("comparison", shapes) == snapshot
    assert cap_process_items("none", shapes) == snapshot


def test_cap_flow_type_also_capped() -> None:
    """`flow` is the same horizontal step layout family as `process`."""
    shapes = _interleaved(_PROCESS_MAX_ITEMS + 2)
    capped = cap_process_items("flow", shapes)
    assert len(_card_texts(capped)) == _PROCESS_MAX_ITEMS


def test_last_kept_card_missing_left_emu_keeps_all_connectors() -> None:
    """Issue #2: if the last KEPT card has no positional info (missing
    ``left_emu``), we have no anchor to decide which connectors dangle, so
    NO connector is pruned — better to keep an arrow than treat an absent
    position as 0 (which would prune every arrow, since left >= 0)."""
    n = _PROCESS_MAX_ITEMS + 3
    shapes = _interleaved(n)
    # Drop the positional key from the card that will become the last kept
    # card (index 7 among cards; in interleaved order that is shape 14).
    card_positions = [
        i for i, s in enumerate(shapes)
        if s.get("type") in ("rounded_rect", "rectangle", "circle")
    ]
    last_keep_shape_idx = card_positions[_PROCESS_MAX_ITEMS - 1]
    del shapes[last_keep_shape_idx]["left_emu"]

    arrows_before = sum(1 for s in shapes if s.get("type") == "arrow")
    capped = cap_process_items("process", shapes)
    arrows_after = sum(1 for s in capped if s.get("type") == "arrow")

    # Cards are still capped + merged exactly as before.
    assert len(_card_texts(capped)) == _PROCESS_MAX_ITEMS
    # With no positional anchor, NO connector is pruned: every arrow in the
    # input survives (overflow CARDS are still merged/removed, but the
    # cap_process_items prune step is disabled). Under the old `or 0` bug
    # this would have pruned every arrow (left >= 0) down to 0.
    assert arrows_after == arrows_before
    assert arrows_after > 0  # would be 0 under the old `or 0` bug


def test_positioned_last_card_still_prunes_orphan_connectors() -> None:
    """Companion to the missing-position case: a normal numeric
    ``left_emu`` on the last kept card still prunes connectors at/after its
    left edge (the orphan arrows that would dangle into dropped cards)."""
    n = _PROCESS_MAX_ITEMS + 3
    shapes = _interleaved(n)

    capped = cap_process_items("process", shapes)

    arrows = [s for s in capped if s.get("type") == "arrow"]
    # Only arrows that sit before the last kept card's left edge survive.
    last_card = next(
        s for s in capped
        if s.get("type") in ("rounded_rect", "rectangle", "circle")
        and " · " in (s.get("text") or "")
    )
    drop_after = last_card["left_emu"]
    assert all(a["left_emu"] < drop_after for a in arrows)
    assert len(arrows) == _PROCESS_MAX_ITEMS - 1
