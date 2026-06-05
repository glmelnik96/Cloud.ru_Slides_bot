#!/usr/bin/env python3
"""
infographic_renderer.py — рендер native_block shapes от infographic_maker.

Зачем: Agent 06 (infographic_maker) производит список абсолютно
позиционированных shapes (rounded_rect + text) — описание визуального
сравнения / списка / процесса / etc. До этого build_v9 хендлил только
``slide_type in (kpi_native, table_native, ...)`` и игнорировал
``plan_slide.infographic.shapes`` — 9 шейпов на слайд молча выкидывались,
и слайд рендерился как «голый текст» в донорском body-плейсхолдере.
Это блокер plan_compliance в visual_verifier (2026-06-05 live run).

Shape spec (как эмиттит Agent 06):
    {
      "type": "rounded_rect" | "text",
      "left_emu", "top_emu", "width_emu", "height_emu",   # int EMU
      "fill_color": "#RRGGBB" | "none",
      "stroke_color": "#RRGGBB" | "none",
      "stroke_width_pt": float,
      "text": str,                                         # может быть ""
      "font": str,                                         # "SB Sans Display"…
      "font_size_pt": int,
      "font_color": "#RRGGBB"
    }
"""
from __future__ import annotations

import sys
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt


_GRAPHITE = RGBColor(0x22, 0x22, 0x22)


def _parse_hex(value: Any) -> RGBColor | None:
    """'#26D07C' / '26D07C' → RGBColor; 'none' / '' / None → None."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip().lstrip("#")
    if not s or s.lower() == "none":
        return None
    if len(s) != 6:
        return None
    try:
        return RGBColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _apply_fill(shape, fill_color: Any) -> None:
    color = _parse_hex(fill_color)
    if color is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = color


def _apply_line(shape, stroke_color: Any, width_pt: Any) -> None:
    color = _parse_hex(stroke_color)
    if color is None:
        shape.line.fill.background()
        return
    shape.line.color.rgb = color
    try:
        w = float(width_pt or 0)
    except (TypeError, ValueError):
        w = 0.0
    if w > 0:
        shape.line.width = Pt(w)


def _set_textframe(tf, text: str, font: str | None, size_pt: Any,
                   color_hex: Any, *, bold: bool = False) -> None:
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    # python-pptx adds a default empty paragraph; reuse it.
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    # Clear any pre-existing runs (cheap — paragraph just created).
    for r in list(p.runs):
        r.text = ""
    run = p.add_run() if not p.runs else p.runs[0]
    run.text = text or ""
    if font:
        run.font.name = font
    try:
        size = int(size_pt) if size_pt is not None else None
    except (TypeError, ValueError):
        size = None
    if size and size > 0:
        run.font.size = Pt(size)
    color = _parse_hex(color_hex) or _GRAPHITE
    run.font.color.rgb = color
    if bold:
        run.font.bold = True


def _emu_bounds(spec: dict[str, Any]) -> tuple[Emu, Emu, Emu, Emu]:
    left = Emu(int(spec.get("left_emu", 0) or 0))
    top = Emu(int(spec.get("top_emu", 0) or 0))
    width = Emu(int(spec.get("width_emu", 0) or 0))
    height = Emu(int(spec.get("height_emu", 0) or 0))
    return left, top, width, height


def _add_filled_shape(slide, spec: dict[str, Any], mso_shape: int,
                     *, rounded_adjust: float | None = None) -> None:
    """Generic add-shape with fill/line/text dispatch.

    Used by rectangle / rounded_rect / circle / arrow — they share the
    same fill+line+optional-text contract; only the MSO_SHAPE constant
    differs. ``rounded_adjust`` overrides the default corner-radius
    fraction (rounded_rect only).
    """
    left, top, width, height = _emu_bounds(spec)
    shape = slide.shapes.add_shape(mso_shape, left, top, width, height)
    if rounded_adjust is not None:
        try:
            shape.adjustments[0] = rounded_adjust
        except Exception:  # noqa: BLE001
            pass
    _apply_fill(shape, spec.get("fill_color"))
    _apply_line(shape, spec.get("stroke_color"), spec.get("stroke_width_pt"))
    text = spec.get("text") or ""
    if text:
        _set_textframe(
            shape.text_frame, text,
            font=spec.get("font"),
            size_pt=spec.get("font_size_pt"),
            color_hex=spec.get("font_color"),
            bold=False,
        )
        tf = shape.text_frame
        tf.margin_left = Emu(60000)
        tf.margin_right = Emu(60000)
        tf.margin_top = Emu(20000)
        tf.margin_bottom = Emu(20000)


def _add_rounded_rect(slide, spec: dict[str, Any]) -> None:
    _add_filled_shape(slide, spec, MSO_SHAPE.ROUNDED_RECTANGLE,
                     rounded_adjust=0.10)


def _add_rectangle(slide, spec: dict[str, Any]) -> None:
    _add_filled_shape(slide, spec, MSO_SHAPE.RECTANGLE)


def _add_circle(slide, spec: dict[str, Any]) -> None:
    _add_filled_shape(slide, spec, MSO_SHAPE.OVAL)


def _add_arrow(slide, spec: dict[str, Any]) -> None:
    """Default to RIGHT_ARROW (process flow l→r). Agent 06 doesn't specify
    direction, but its `process` infographic_type uses horizontal step
    layouts where arrows go left→right between boxes."""
    _add_filled_shape(slide, spec, MSO_SHAPE.RIGHT_ARROW)


def _add_line(slide, spec: dict[str, Any]) -> None:
    """Render as a thin rectangle (height = stroke_width). python-pptx
    Connector API is brittle for absolute positions in this codebase,
    and Agent 06 emits line shapes with full bounding boxes anyway."""
    left, top, width, height = _emu_bounds(spec)
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    # Lines have no fill — colour comes from stroke_color (use as fill).
    stroke_hex = spec.get("stroke_color") or spec.get("fill_color")
    color = _parse_hex(stroke_hex)
    if color is not None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = color
    else:
        shape.fill.background()
    shape.line.fill.background()


def _add_textbox(slide, spec: dict[str, Any]) -> None:
    left = Emu(int(spec.get("left_emu", 0) or 0))
    top = Emu(int(spec.get("top_emu", 0) or 0))
    width = Emu(int(spec.get("width_emu", 0) or 0))
    height = Emu(int(spec.get("height_emu", 0) or 0))
    box = slide.shapes.add_textbox(left, top, width, height)
    _apply_fill(box, spec.get("fill_color"))
    # Textboxes generally render lines as nuisance; only draw if explicit.
    _apply_line(box, spec.get("stroke_color"), spec.get("stroke_width_pt"))
    _set_textframe(
        box.text_frame, spec.get("text") or "",
        font=spec.get("font"),
        size_pt=spec.get("font_size_pt"),
        color_hex=spec.get("font_color"),
    )


_HANDLERS = {
    "rounded_rect": _add_rounded_rect,
    "rectangle":    _add_rectangle,
    "circle":       _add_circle,
    "arrow":        _add_arrow,
    "line":         _add_line,
    "text":         _add_textbox,
}


def render_infographic_shapes(slide, shapes: list[dict[str, Any]]) -> int:
    """Inject Agent 06 shape specs onto an existing (cloned) donor slide.

    Returns the count of shapes successfully added. Unknown types are
    logged and skipped — we never raise, because losing one shape is
    better than failing the entire build.
    """
    if not shapes:
        return 0
    added = 0
    for i, spec in enumerate(shapes):
        if not isinstance(spec, dict):
            print(f"WARN: infographic shape #{i} is not a dict ({type(spec).__name__})",
                  file=sys.stderr)
            continue
        kind = spec.get("type")
        handler = _HANDLERS.get(kind)
        if handler is None:
            print(f"WARN: infographic shape #{i} unknown type {kind!r}",
                  file=sys.stderr)
            continue
        try:
            handler(slide, spec)
            added += 1
        except Exception as e:  # noqa: BLE001 — never fail the build
            print(f"WARN: infographic shape #{i} ({kind}) failed: {e}",
                  file=sys.stderr)
    return added


# Slots that infographic shapes are expected to replace on the donor.
# Title stays (the infographic_maker doesn't reproduce slide titles).
# Anything else with text → cleared so the body doesn't bleed through
# under translucent infographic blocks.
_BODY_SLOT_KEYWORDS = (
    "body", "content", "caption", "subtitle", "description", "desc",
    "text", "list", "card", "col1", "col2", "col3", "col4", "col5", "col6",
    "annotation", "left", "right", "top", "bottom", "center",
)


def clear_donor_body_slots(slide, donor_def: dict[str, Any] | None) -> int:
    """Empty text frames of donor body-like slots — leaves title intact.

    Called when infographic shapes are about to be injected so the
    donor's pre-rendered body text doesn't show through between/around
    the new blocks. Returns count of slots cleared.
    """
    if not donor_def:
        return 0
    slots = donor_def.get("slots") or {}
    if not isinstance(slots, dict):
        return 0

    # Need lazy import — build_v5 sits next to this file and pulls pptx
    # at import time, which is fine inside the package but not in
    # isolated tests that don't ship build_v5.
    from build_v5 import get_text_frame_by_shape_idx, clear_text_frame

    cleared = 0
    for slot_name, slot_def in slots.items():
        name_low = (slot_name or "").lower()
        # Keep title — infographic_maker doesn't reproduce slide titles.
        if "title" in name_low and "subtitle" not in name_low:
            continue
        if not any(kw in name_low for kw in _BODY_SLOT_KEYWORDS):
            continue
        if not isinstance(slot_def, dict):
            continue
        idx = slot_def.get("shape_idx")
        if idx is None:
            continue
        tf = get_text_frame_by_shape_idx(slide, idx)
        if tf is None:
            continue
        try:
            clear_text_frame(tf)
            cleared += 1
        except Exception as e:  # noqa: BLE001
            print(f"WARN: clear donor slot {slot_name!r} (idx={idx}) failed: {e}",
                  file=sys.stderr)
    return cleared


# D1+D8 fix (2026-06-05): when injecting Agent 06's infographic shapes onto
# a donor template, the donor often has its own pre-labeled boxes (process
# steps, comparison cells) whose text isn't in the donor slot map — it lives
# as plain text inside shapes that decorate the layout. The previous
# `clear_donor_body_slots` only touched slot-mapped shapes, so donor labels
# bled through and overlapped Agent 06's new labels (run1.slide7: "Recorder"
# overlap "Хранение данных"). This is a more aggressive pass: clear *all*
# non-title text on the slide, regardless of slot mapping.

# Heuristic font-size threshold for "this is title-like" — donor titles are
# typically 20pt+, body labels are 12-16pt. Conservative: keep anything 18pt+.
_TITLE_FONT_PT_MIN = 18.0


def _shape_is_title_like(shape) -> bool:
    """Title detection independent of donor slot maps. Uses placeholder type
    when available, otherwise the largest run font size. Mirrors the heuristic
    in kpi_emphasis._shape_is_title_like but standalone (cyclic import-safe).
    """
    try:
        ph = shape.placeholder_format
        if ph is not None:
            from pptx.enum.shapes import PP_PLACEHOLDER
            if ph.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE,
                           PP_PLACEHOLDER.VERTICAL_TITLE):
                return True
    except (ValueError, AttributeError):
        pass
    if not getattr(shape, "has_text_frame", False):
        return False
    # Largest font on any run — title rows usually have big numbers.
    max_pt = 0.0
    try:
        for p in shape.text_frame.paragraphs:
            for r in p.runs:
                try:
                    if r.font.size is not None:
                        max_pt = max(max_pt, float(r.font.size.pt))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        return False
    return max_pt >= _TITLE_FONT_PT_MIN


def clear_donor_non_title_text(slide) -> int:
    """Strip text from every non-title shape on the slide.

    Run before injecting infographic shapes so donor decoration labels
    (process-step names, comparison cells, etc.) don't overlap the new
    Agent 06 boxes. Title remains; everything else loses its text but
    keeps its visual shape (fill/stroke). Recurses into groups and
    table cells so the cleanup is complete.

    Returns count of shapes whose text was cleared.
    """
    cleared = 0
    try:
        from build_v5 import clear_text_frame
    except ImportError:
        return 0

    def _walk(shapes):
        nonlocal cleared
        for sh in shapes:
            # Groups: recurse.
            try:
                if sh.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
                    _walk(sh.shapes)
                    continue
            except Exception:  # noqa: BLE001
                pass
            # Tables: blank every cell text frame (table itself is decoration).
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for cell in row.cells:
                        try:
                            clear_text_frame(cell.text_frame)
                            cleared += 1
                        except Exception:  # noqa: BLE001
                            pass
                continue
            if not getattr(sh, "has_text_frame", False):
                continue
            if _shape_is_title_like(sh):
                continue
            text = (sh.text_frame.text or "").strip()
            if not text:
                continue
            try:
                clear_text_frame(sh.text_frame)
                cleared += 1
            except Exception as e:  # noqa: BLE001
                print(f"WARN: clear_donor_non_title_text failed: {e}",
                      file=sys.stderr)

    _walk(slide.shapes)
    return cleared
