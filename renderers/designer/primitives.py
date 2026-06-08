"""Native python-pptx vector primitives for the Cloud.ru 2.0 designer skill.

Every primitive draws editable native shapes (autoshapes, textboxes, native
charts, freeforms) — NO raster bake. Colors/fonts come from the brand glossary
in llm.prompts._shared so the skill and the prompts share one source of truth.

q2 prototype scope: enough primitives to render the data-chart and KPI
archetypes end-to-end and prove the DSL->native path.
"""
from __future__ import annotations

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

# Brand glossary (single source of truth). Fall back to literals if the import
# path shifts during prototyping.
try:
    from llm.prompts._shared import (
        BRAND_PALETTE,
        EMU_PER_PX,
        PRIMARY_FONT,
        SEMIBOLD_FONT,
    )
except Exception:  # pragma: no cover - prototype safety net
    EMU_PER_PX = 9525
    PRIMARY_FONT = "SB Sans Display"
    SEMIBOLD_FONT = "SB Sans Display Semibold"
    BRAND_PALETTE = {
        "green": "#26D07C", "graphite": "#222222", "gray": "#F2F2F2",
        "white": "#FFFFFF", "stroke": "#C8C8C8",
    }

GREEN = RGBColor.from_string(BRAND_PALETTE["green"].lstrip("#"))
GRAPHITE = RGBColor.from_string(BRAND_PALETTE["graphite"].lstrip("#"))
GRAY = RGBColor.from_string(BRAND_PALETTE["gray"].lstrip("#"))
WHITE = RGBColor.from_string(BRAND_PALETTE["white"].lstrip("#"))

# Pastel ramp for non-accent chart series (brandbook: only ONE green accent).
# Muted, low-saturation, never competes with green.
NON_ACCENT = [
    RGBColor.from_string("BFC7CE"),  # cool gray-blue
    RGBColor.from_string("D8DDE1"),  # lighter gray
    RGBColor.from_string("9AA4AD"),  # darker gray
    RGBColor.from_string("E5E8EB"),
]


def px(v: float) -> Emu:
    return Emu(int(round(v * EMU_PER_PX)))


def _no_line(shape) -> None:
    shape.line.fill.background()


def _solid(shape, color: RGBColor) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = color


# ─── Backgrounds ─────────────────────────────────────────────────────────────

def background(slide, kind: str) -> None:
    """Full-bleed background rectangle (Group A brand plashka)."""
    color = {
        "white": WHITE, "graphite": GRAPHITE, "green": GREEN, "dots": WHITE,
    }.get(kind, WHITE)
    rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, px(1280), px(720))
    _solid(rect, color)
    _no_line(rect)
    # Send to back so content draws over it.
    sp = rect._element
    sp.getparent().remove(sp)
    slide.shapes._spTree.insert(2, sp)
    if kind == "dots":
        _dot_pattern(slide)


def _dot_pattern(slide, step_px: int = 120, dot_px: int = 4) -> None:
    """Sparse dot texture (brandbook p.26).

    q2 fix: the original 40px step emitted ~480 ovals (file bloat). The lattice
    is now coarse and HARD-CAPPED so a dots background never exceeds ~60 shapes.
    """
    light = RGBColor.from_string("ECEEF0")
    cap, drawn = 60, 0
    y = 60
    while y < 700 and drawn < cap:
        x = 60
        while x < 1240 and drawn < cap:
            d = slide.shapes.add_shape(MSO_SHAPE.OVAL, px(x), px(y), px(dot_px), px(dot_px))
            _solid(d, light)
            _no_line(d)
            drawn += 1
            x += step_px
        y += step_px


# ─── Text ────────────────────────────────────────────────────────────────────

def title_block(slide, text: str, rect_px, size_pt: int = 44,
                accent_underline: bool = True, dark_bg: bool = False) -> None:
    left, top, w, h = rect_px
    if accent_underline:
        # Green plashka-underline under the baseline (accent is an ELEMENT,
        # never the letter color — canonical rule).
        und = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, px(left), px(top + h - 6), px(min(w, 120)), px(8)
        )
        _solid(und, GREEN)
        _no_line(und)
    tb = slide.shapes.add_textbox(px(left), px(top), px(w), px(h))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.name = SEMIBOLD_FONT
    run.font.size = Pt(size_pt)
    run.font.color.rgb = WHITE if dark_bg else GRAPHITE
    return tb


def body_block(slide, bullets, rect_px, size_pt: int = 16, dark_bg: bool = False):
    left, top, w, h = rect_px
    tb = slide.shapes.add_textbox(px(left), px(top), px(w), px(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = f"— {b}"
        run.font.name = PRIMARY_FONT
        run.font.size = Pt(size_pt)
        run.font.color.rgb = WHITE if dark_bg else GRAPHITE
        p.space_after = Pt(6)
    return tb


def kpi_block(slide, num: str, desc: str, rect_px, dark_bg: bool = False):
    """KPI: big graphite number + small desc. Number is text color graphite,
    NOT green (canonical: green is an element, not letters)."""
    left, top, w, h = rect_px
    big = slide.shapes.add_textbox(px(left), px(top), px(w), px(h * 0.6))
    tf = big.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = num
    r.font.name = SEMIBOLD_FONT
    r.font.size = Pt(72)
    r.font.color.rgb = WHITE if dark_bg else GRAPHITE
    small = slide.shapes.add_textbox(px(left), px(top + h * 0.6), px(w), px(h * 0.4))
    tf2 = small.text_frame
    tf2.word_wrap = True
    p2 = tf2.paragraphs[0]
    r2 = p2.add_run()
    r2.text = desc
    r2.font.name = PRIMARY_FONT
    r2.font.size = Pt(14)
    r2.font.color.rgb = WHITE if dark_bg else GRAPHITE
    return big


# ─── Charts (native, Excel-editable) ─────────────────────────────────────────

_CHART_MAP = {
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "pie": XL_CHART_TYPE.PIE,
    "area_100": XL_CHART_TYPE.AREA_STACKED_100,
}


def chart_block(slide, chart_type, categories, series, rect_px, accent_idx=0,
                data_provenance="native"):
    left, top, w, h = rect_px
    if data_provenance == "estimated":
        # A report must never silently present read-off numbers as exact.
        h = max(h - 24, 24)
        fn = slide.shapes.add_textbox(px(left), px(top + h), px(w), px(20))
        rp = fn.text_frame.paragraphs[0]
        rr = rp.add_run()
        rr.text = "оценка по графику"
        rr.font.name = PRIMARY_FONT
        rr.font.size = Pt(9)
        rr.font.italic = True
        rr.font.color.rgb = RGBColor.from_string("9AA4AD")
    data = CategoryChartData()
    data.categories = categories
    for s in series:
        data.add_series(s["name"], s["values"])
    gframe = slide.shapes.add_chart(
        _CHART_MAP.get(chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED),
        px(left), px(top), px(w), px(h), data,
    )
    chart = gframe.chart
    chart.has_title = False
    # Recolor: exactly one green accent series, rest pastel (brandbook rule).
    plot = chart.plots[0]
    if chart_type == "pie":
        pts = plot.series[0].points
        for i, pt in enumerate(pts):
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = GREEN if i == accent_idx else NON_ACCENT[i % len(NON_ACCENT)]
    else:
        for i, ser in enumerate(plot.series):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = GREEN if i == accent_idx else NON_ACCENT[i % len(NON_ACCENT)]
    if len(series) > 1:
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    else:
        chart.has_legend = False
    return gframe


# ─── Decor (outline) ─────────────────────────────────────────────────────────

def outline_corner(slide, anchor: str, dark_bg: bool = False):
    """Thin L-shaped corner bracket (outline-decor obvyazka, ~2px)."""
    color = WHITE if dark_bg else GRAPHITE
    size, off, thick = 60, 40, 2
    pos = {
        "top_left": (off, off, 1, 1),
        "top_right": (1280 - off - size, off, -1, 1),
        "bottom_left": (off, 720 - off - size, 1, -1),
        "bottom_right": (1280 - off - size, 720 - off - size, -1, -1),
    }[anchor]
    x, y, sx, sy = pos
    # horizontal arm
    hor = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(x), px(y), px(size), px(thick))
    _solid(hor, color); _no_line(hor)
    # vertical arm
    ver = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(x), px(y), px(thick), px(size))
    _solid(ver, color); _no_line(ver)


def sparkle(slide, anchor: str, dark_bg: bool = False):
    """Small 4-point spark (brandbook sparkle motif), drawn as a freeform."""
    color = WHITE if dark_bg else GREEN  # the one green accent on light bg
    off, s = 50, 34
    base = {
        "top_left": (off, off), "top_right": (1280 - off - s, off),
        "bottom_left": (off, 720 - off - s), "bottom_right": (1280 - off - s, 720 - off - s),
    }[anchor]
    bx, by = base
    cx, cy = bx + s / 2, by + s / 2
    fb = slide.shapes.build_freeform(px(cx), px(by), scale=1)
    pts = [
        (cx + s * 0.12, cy - s * 0.12), (bx + s, cy), (cx + s * 0.12, cy + s * 0.12),
        (cx, by + s), (cx - s * 0.12, cy + s * 0.12), (bx, cy),
        (cx - s * 0.12, cy - s * 0.12), (cx, by),
    ]
    fb.add_line_segments([(px(x), px(y)) for x, y in pts], close=True)
    shp = fb.convert_to_shape()
    _solid(shp, color)
    _no_line(shp)
    return shp


# ─── Portal (stepped black graphic, brandbook pp.29-33) ──────────────────────

# Staircase offset per step as a fraction of the square side (PDF: +~24% right,
# -~7.5% up). Squares are identical; later squares z-order on top.
_PORTAL_DX, _PORTAL_DY = 0.24, 0.075


def portal(slide, base_rect_px, n: int = 3):
    """N identical #222222 squares in an up-right staircase (brand 'портал').

    base_rect_px gives the bottom-left square's (left, top, side) — width is the
    side; the staircase grows up and to the right from there.
    """
    left, top, side = base_rect_px
    shapes = []
    for i in range(max(1, n)):
        x = left + i * _PORTAL_DX * side
        y = top - i * _PORTAL_DY * side
        sq = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(x), px(y), px(side), px(side))
        _solid(sq, GRAPHITE)
        _no_line(sq)
        shapes.append(sq)
    return shapes


# ─── Diagram primitives (nodes + arrows) ─────────────────────────────────────

def node_box(slide, text: str, rect_px, accent: bool = False, dark_bg: bool = False):
    """Labelled diagram node: rounded-rect (<=4px) plate + centered text."""
    left, top, w, h = rect_px
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, px(left), px(top), px(w), px(h))
    # Clamp corner radius to brand <=4px (adjustment is a fraction of short side).
    try:
        box.adjustments[0] = min(4.0 / min(w, h), 0.1)
    except Exception:  # pragma: no cover - guard against pptx version drift
        pass
    if accent:
        _solid(box, GREEN)
        txt_color = GRAPHITE
    else:
        _solid(box, GRAPHITE if dark_bg else GRAY)
        txt_color = WHITE if dark_bg else GRAPHITE
    _no_line(box)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.name = SEMIBOLD_FONT
    r.font.size = Pt(14)
    r.font.color.rgb = txt_color
    return box


def _set_arrow_head(connector) -> None:
    """Add a triangular tail arrowhead to a connector's line (XML, no API)."""
    ln = connector.line._get_or_add_ln()
    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)


def arrow(slide, p0_px, p1_px, rhombus: bool = False, dark_bg: bool = False):
    """Directed connector p0 -> p1, square cap + triangle head.

    If rhombus=True, seat a 45° green square at the midpoint as a brand backing
    (its fill MUST differ from the line color — line stays graphite/white)."""
    x0, y0 = p0_px
    x1, y1 = p1_px
    line_color = WHITE if dark_bg else GRAPHITE
    if rhombus:
        s = 22
        mx, my = (x0 + x1) / 2 - s / 2, (y0 + y1) / 2 - s / 2
        dia = slide.shapes.add_shape(MSO_SHAPE.DIAMOND, px(mx), px(my), px(s), px(s))
        _solid(dia, GREEN)
        _no_line(dia)
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, px(x0), px(y0), px(x1), px(y1))
    conn.line.color.rgb = line_color
    conn.line.width = Emu(int(2 * EMU_PER_PX))  # 2px micromodule
    _set_arrow_head(conn)
    return conn


# ─── Cards (team / comparison) ───────────────────────────────────────────────

def person_card(slide, heading: str, sub: str, rect_px, plate: bool = True,
                accent: bool = False, dark_bg: bool = False):
    """Card: optional backing plate + heading (SemiBold) + sub line."""
    left, top, w, h = rect_px
    if plate:
        pl = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(left), px(top), px(w), px(h * 0.55))
        _solid(pl, GREEN if accent else (GRAPHITE if dark_bg else GRAY))
        _no_line(pl)
    tb = slide.shapes.add_textbox(px(left), px(top + h * 0.58), px(w), px(h * 0.42))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = heading
    r.font.name = SEMIBOLD_FONT
    r.font.size = Pt(16)
    r.font.color.rgb = WHITE if dark_bg else GRAPHITE
    if sub:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = sub
        r2.font.name = PRIMARY_FONT
        r2.font.size = Pt(12)
        r2.font.color.rgb = WHITE if dark_bg else GRAPHITE
    return tb


# ─── Timeline ────────────────────────────────────────────────────────────────

def milestone_tick(slide, label: str, text: str, rect_px, accent: bool = False,
                   dark_bg: bool = False):
    """One milestone: small square tick + label + one-line text under it."""
    left, top, w, h = rect_px
    tick = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(left), px(top), px(12), px(12))
    _solid(tick, GREEN if accent else (WHITE if dark_bg else GRAPHITE))
    _no_line(tick)
    tb = slide.shapes.add_textbox(px(left), px(top + 18), px(w), px(h - 18))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = label
    r.font.name = SEMIBOLD_FONT
    r.font.size = Pt(18)
    r.font.color.rgb = WHITE if dark_bg else GRAPHITE
    if text:
        p2 = tf.add_paragraph()
        r2 = p2.add_run()
        r2.text = text
        r2.font.name = PRIMARY_FONT
        r2.font.size = Pt(12)
        r2.font.color.rgb = WHITE if dark_bg else GRAPHITE
    return tb


def timeline_axis(slide, y_px: int, x0_px: int = 60, x1_px: int = 1220,
                  dark_bg: bool = False):
    """Thin horizontal axis line for the timeline archetype."""
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, px(x0_px), px(y_px),
                                      px(x1_px), px(y_px))
    conn.line.color.rgb = WHITE if dark_bg else RGBColor.from_string("C8C8C8")
    conn.line.width = Emu(int(2 * EMU_PER_PX))
    return conn
