"""Deterministic Composition(DSL) -> native python-pptx slide assembler.

The LLM emits Composition objects on a 12x10 grid; this module turns each
block into native vector shapes via `primitives`. No EMU, no placeholder
indices ever reach the LLM. This is the q2-prototype renderer.
"""
from __future__ import annotations

from pptx import Presentation
from pptx.util import Emu

from renderers.designer import primitives as P
from renderers.designer.composition_dsl import (
    Composition,
    GRID_COLS,
    GRID_ROWS,
    Grid,
)

CANVAS_W, CANVAS_H = 1280, 720
MARGIN = 40  # safe-area margin in px (brandbook micro-module multiple)
# Brand safe-area bottom is 660px; reserve a larger bottom margin so a block in
# the last grid row (r=10) never bleeds past it (was ending at 680px).
MARGIN_BOTTOM = 60


def _snap2(v: float) -> float:
    """Snap to the 2px brand micromodule (every offset divisible by 2)."""
    return round(v / 2.0) * 2.0


def _grid_to_px(g: Grid):
    """Convert a grid span to a px rect inside the safe area (2px-snapped)."""
    usable_w = CANVAS_W - 2 * MARGIN
    usable_h = CANVAS_H - MARGIN - MARGIN_BOTTOM
    cell_w = usable_w / GRID_COLS
    cell_h = usable_h / GRID_ROWS
    left = MARGIN + (g.c - 1) * cell_w
    top = MARGIN + (g.r - 1) * cell_h
    w = g.cs * cell_w
    h = g.rs * cell_h
    return (_snap2(left), _snap2(top), _snap2(w), _snap2(h))


def _edge_point(rect, toward):
    """Point on ``rect``'s border along the line from its center to ``toward``.

    Keeps connector endpoints on the node boundary so arrows touch the boxes
    instead of cutting through their centers.
    """
    left, top, w, h = rect
    cx, cy = left + w / 2, top + h / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    if dx == 0 and dy == 0:
        return (cx, cy)
    hw, hh = w / 2, h / 2
    sx = hw / abs(dx) if dx else float("inf")
    sy = hh / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return (cx + dx * s, cy + dy * s)


def _portal_base(anchor: str, side: float = 200.0):
    """Bottom-left (left, top, side) for a portal staircase anchored to a corner.

    The staircase grows up-and-right, so leave room above and to the right.
    """
    pad = 40
    grow_w = side * (1 + 2 * 0.24)
    grow_up = side * (1 + 2 * 0.075)
    pos = {
        "top_left": (pad, pad + grow_up - side),
        "top_right": (CANVAS_W - pad - grow_w, pad + grow_up - side),
        "bottom_left": (pad, CANVAS_H - pad - side),
        "bottom_right": (CANVAS_W - pad - grow_w, CANVAS_H - pad - side),
    }[anchor]
    return (pos[0], pos[1], side)


def assemble_slide(prs: Presentation, comp: Composition) -> None:
    blank = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(blank)
    dark = comp.tone == "dark" or comp.background.kind == "graphite"

    P.background(slide, comp.background.kind)

    # First pass: resolve node rects so connectors can route edge-to-edge.
    node_rects: list[tuple[float, float, float, float]] = []
    for blk in comp.blocks:
        if blk.role == "node":
            node_rects.append(_grid_to_px(blk.grid))
    node_centers = [(l + w / 2, t + h / 2) for (l, t, w, h) in node_rects]

    for blk in comp.blocks:
        role = blk.role
        if role == "decor":
            if blk.kind == "sparkle":
                P.sparkle(slide, blk.anchor, dark_bg=dark)
            elif blk.kind == "outline_corner":
                P.outline_corner(slide, blk.anchor, dark_bg=dark)
            elif blk.kind == "portal":
                P.portal(slide, _portal_base(blk.anchor), n=blk.portal_squares,
                         dark_bg=dark)
            continue
        if role == "connector":
            if 0 <= blk.src < len(node_centers) and 0 <= blk.dst < len(node_centers):
                p0 = _edge_point(node_rects[blk.src], node_centers[blk.dst])
                p1 = _edge_point(node_rects[blk.dst], node_centers[blk.src])
                P.arrow(slide, p0, p1, rhombus=blk.rhombus, dark_bg=dark)
            continue
        rect = _grid_to_px(blk.grid)
        if role == "title":
            P.title_block(slide, blk.text, rect, size_pt=blk.size_pt,
                          accent_underline=blk.accent_underline, dark_bg=dark)
        elif role == "body":
            P.body_block(slide, blk.bullets, rect, size_pt=blk.size_pt, dark_bg=dark)
        elif role == "kpi":
            P.kpi_block(slide, blk.num, blk.desc, rect, dark_bg=dark)
        elif role == "chart":
            P.chart_block(
                slide, blk.chart_type, blk.categories,
                [s.model_dump() for s in blk.series], rect, accent_idx=blk.accent_idx,
                data_provenance=blk.data_provenance, dark_bg=dark,
            )
        elif role == "table":
            P.table_block(
                slide, blk.headers, blk.rows, rect,
                accent_col=blk.accent_col, first_col_wider=blk.first_col_wider,
                dark_bg=dark,
            )
        elif role == "node":
            P.node_box(slide, blk.text, rect, accent=blk.accent, dark_bg=dark)
        elif role == "card":
            P.person_card(slide, blk.heading, blk.sub, rect, plate=blk.plate,
                          accent=blk.accent, dark_bg=dark)
        elif role == "milestone":
            P.milestone_tick(slide, blk.label, blk.text, rect, accent=blk.accent,
                             dark_bg=dark)


def build_deck(comps: list[Composition], out_path: str) -> str:
    prs = Presentation()
    prs.slide_width = Emu(CANVAS_W * P.EMU_PER_PX)
    prs.slide_height = Emu(CANVAS_H * P.EMU_PER_PX)
    for comp in comps:
        assemble_slide(prs, comp)
    prs.save(out_path)
    return out_path
