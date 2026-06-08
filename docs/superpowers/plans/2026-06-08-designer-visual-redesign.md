# Designer Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the visual gap between `/design` output and the Cloud.ru reference template by making the skill act like a designer: branded archetype skeletons own the layout, and four vision steps let the skill see the source, target a brand exemplar, critique its own render, and review the deck.

**Architecture:** Keep the standalone `designer_graph`. Replace blind 12×10 block placement with **archetype skeletons** (`renderers/designer/layouts.py`) that lay out named zones with brand dressing. The composer emits CONTENT keyed by zone, not coordinates. Add a render→PNG visual-QA loop (Kimi `PIXEL_JUDGE`) and a deck-level review (Kimi `VISUAL_VERIFIER`). Source-slide vision feeds archetype choice; a brand-exemplar PNG feeds the composer.

**Tech Stack:** python-pptx (native vector), LibreOffice headless (`soffice --convert-to pdf`), PyMuPDF/`fitz` (PDF→PNG), Cloud.ru FM API (GLM-5.1 text, Kimi-K2.6 vision), LangGraph, Pydantic.

**Validation philosophy (USER MANDATE — overrides default TDD):** Every change is validated **visually** by rendering the affected slide(s) to PNG and inspecting them against the brand reference — NOT by unit tests. Each task's verification step is "render → read PNG → confirm it matches the reference." Commit after each visually-accepted task.

**Working directory:** `C:\Users\Глеб\Documents\Slides_bot_design` (worktree, branch `feature/designer-skill`). All paths below are relative to it.

---

## Phase 0 — Visual validation harness

The whole plan depends on a fast, repeatable "render one deck/slide to PNG and look at it" loop. Build it first.

### Task 0: Render-to-PNG harness

**Files:**
- Create: `scripts/render_png.py`
- Reference (read-only): `scripts/reassemble_design.py` (LibreOffice/skill_bridge pattern)

- [ ] **Step 1: Write the harness**

```python
"""Render a .pptx to per-slide PNGs for visual validation.

Usage: python -m scripts.render_png <deck.pptx> [out_dir] [--zoom 1.5]
Writes <out_dir>/<stem>_s{N}.png (1-based). Prints the paths so the agent
can Read each PNG and visually compare against the brand reference.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz  # PyMuPDF

SOFFICE = "soffice"  # on PATH; Windows: LibreOffice\program\soffice.exe


def pptx_to_pdf(pptx: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [SOFFICE, "--headless", "--convert-to", "pdf", "--outdir",
         str(out_dir), str(pptx)],
        check=True, timeout=180,
    )
    pdf = out_dir / (pptx.stem + ".pdf")
    if not pdf.is_file():
        raise RuntimeError(f"LibreOffice did not produce {pdf}")
    return pdf


def pdf_to_pngs(pdf: Path, out_dir: Path, stem: str, zoom: float) -> list[Path]:
    doc = fitz.open(pdf)
    mat = fitz.Matrix(zoom, zoom)
    paths: list[Path] = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=mat)
        p = out_dir / f"{stem}_s{i}.png"
        p.write_bytes(pix.tobytes("png"))
        paths.append(p)
    doc.close()
    return paths


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.render_png <deck.pptx> [out_dir] [--zoom Z]",
              file=sys.stderr)
        return 2
    pptx = Path(sys.argv[1])
    if not pptx.is_file():
        print(f"ERROR: not found: {pptx}", file=sys.stderr)
        return 2
    zoom = 1.5
    args = [a for a in sys.argv[2:]]
    if "--zoom" in args:
        zi = args.index("--zoom")
        zoom = float(args[zi + 1])
        del args[zi:zi + 2]
    out_dir = Path(args[0]) if args else pptx.parent / "png"
    pdf = pptx_to_pdf(pptx, out_dir)
    pngs = pdf_to_pngs(pdf, out_dir, pptx.stem, zoom)
    for p in pngs:
        print(p, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it renders an existing deck**

Run: `python -m scripts.render_png tmp/design_out/<any-existing>_design.pptx tmp/png_check`
Expected: prints one PNG path per slide; files exist.

- [ ] **Step 3: Visually confirm** — Read 1-2 of the emitted PNGs. Confirm slides are legible (this is the baseline "naked python-pptx" look we are fixing).

- [ ] **Step 4: Commit**

```bash
git add scripts/render_png.py
git commit -m "feat(designer): add render-to-PNG harness for visual validation"
```

### Task 0b: Brand exemplar PNGs (reference few-shot source)

The reference few-shot (vision point 2) needs one PNG per archetype rendered from the template. The references dir is currently empty.

**Files:**
- Create: `skill_assets/brand/references/exemplars/` (PNG output dir)
- Create: `scripts/build_exemplars.py`
- Reference (read-only): `skill_assets/brand/Cloud.ru_Template_2026.pptx`, `skill_assets/brand/template-slides-catalog.json`

- [ ] **Step 1: Map archetype → reference page.** Read `template-slides-catalog.json` and pick the cleanest template page for each archetype. Starting map (refine by eye in Step 3):

```python
# scripts/build_exemplars.py
"""Render the chosen reference template pages to per-archetype exemplar PNGs.

These feed the composer as a vision few-shot ("target this look").
Usage: python -m scripts.build_exemplars
"""
from __future__ import annotations

from pathlib import Path

import fitz

TEMPLATE = Path("skill_assets/brand/Cloud.ru_Template_2026.pptx")
OUT = Path("skill_assets/brand/references/exemplars")

# archetype -> 1-based template page number (refined visually in Task 0b step 3)
ARCHETYPE_PAGE = {
    "cover_green": 1,
    "cover_dark": 6,
    "cover_photo": 5,
    "section_divider": 6,
    "points_3": 36,
    "points_4": 36,
    "points_6": 36,
    "points_8": 36,
    "bullet_list": 36,
    "table_zebra": 52,
    "chart_columns": 45,
    "roadmap_timeline": 61,
}


def main() -> int:
    from scripts.render_png import pptx_to_pdf
    OUT.mkdir(parents=True, exist_ok=True)
    pdf = pptx_to_pdf(TEMPLATE, OUT)
    doc = fitz.open(pdf)
    mat = fitz.Matrix(1.5, 1.5)
    for arch, page_no in ARCHETYPE_PAGE.items():
        page = doc[page_no - 1]
        (OUT / f"{arch}.png").write_bytes(page.get_pixmap(matrix=mat).tobytes("png"))
        print(f"{arch} <- p{page_no}", flush=True)
    doc.close()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 2: Run** `python -m scripts.build_exemplars`. Expected: one PNG per archetype in `skill_assets/brand/references/exemplars/`.

- [ ] **Step 3: Visually verify each exemplar.** Read each emitted PNG. For any that doesn't clearly show the intended layout (e.g. `points_3` page lacks the green-divider 3-point look), find a better page in the template (Read the template via `render_png` of the whole template) and fix `ARCHETYPE_PAGE`, re-run. Repeat until each exemplar is a clean, representative brand example.

- [ ] **Step 4: Commit**

```bash
git add scripts/build_exemplars.py skill_assets/brand/references/exemplars/
git commit -m "feat(designer): render brand archetype exemplar PNGs for vision few-shot"
```

---

## Phase 1 — Brand vocabulary refinements (primitives.py)

Add the signature elements that read as "Cloud.ru". Each is validated by rendering a tiny probe deck.

### Task 1: `divider_line` primitive (green keyline above an item)

**Files:**
- Modify: `renderers/designer/primitives.py`

- [ ] **Step 1: Add the primitive** (append near `_accent_bar`, ~line 209):

```python
def divider_line(slide, left, top, w, *, color=GREEN, thick: int = 4):
    """Green horizontal keyline used above a bold sub-head + text item.

    This is the core "N points" brand motif (template p.36): a short green
    rule sits directly above each point's heading. Square caps, no effects.
    """
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, px(left), px(top), px(w), px(thick))
    _solid(bar, color)
    _no_line(bar)
    return bar
```

- [ ] **Step 2: Add a point-item helper** (heading + body under a divider; append after `divider_line`):

```python
def point_item(slide, heading: str, text: str, rect_px, *, dark_bg: bool = False):
    """One "point": green divider rule, bold sub-head, body text beneath it
    (template p.36 module). Lays out inside rect_px with the divider on top.
    """
    left, top, w, h = rect_px
    divider_line(slide, left, top, min(w, 56))
    color = WHITE if dark_bg else GRAPHITE
    head_h = h * 0.34
    h_pt, _, _ = _fit(str(heading), w, head_h, base_pt=20.0, min_pt=13.0,
                      semibold=True, wrap=True)
    hb = slide.shapes.add_textbox(px(left), px(top + 12), px(w), px(head_h))
    htf = hb.text_frame
    htf.word_wrap = True
    _zero_margins(htf)
    hp = htf.paragraphs[0]
    hr = hp.add_run()
    hr.text = heading
    hr.font.name = SEMIBOLD_FONT
    hr.font.size = Pt(h_pt)
    hr.font.color.rgb = color
    if text:
        body_top = top + 12 + head_h + 6
        body_h = h - (body_top - top)
        b_pt, _, _ = _fit(str(text), w, body_h, base_pt=15.0, min_pt=10.0,
                          semibold=False, wrap=True)
        bb = slide.shapes.add_textbox(px(left), px(body_top), px(w), px(body_h))
        btf = bb.text_frame
        btf.word_wrap = True
        _zero_margins(btf)
        bp = btf.paragraphs[0]
        br = bp.add_run()
        br.text = text
        br.font.name = PRIMARY_FONT
        br.font.size = Pt(b_pt)
        br.font.color.rgb = TEXT_GRAY if not dark_bg else WHITE
    return hb
```

- [ ] **Step 3: Render a probe.** Create `tmp/probe_points.py`:

```python
from pptx import Presentation
from pptx.util import Emu
from renderers.designer import primitives as P
from worker import skill_bridge
skill_bridge.install()
prs = Presentation()
prs.slide_width = Emu(1280 * P.EMU_PER_PX)
prs.slide_height = Emu(720 * P.EMU_PER_PX)
s = prs.slides.add_slide(prs.slide_layouts[6])
P.background(s, "white")
P.title_block(s, "Три направления развития", (40, 40, 1000, 120))
cells = [
    ("Инфраструктура", "Масштабируемые вычисления и хранение в едином контуре."),
    ("Платформа", "Управляемые сервисы данных, ML и контейнеров."),
    ("Экосистема", "Маркетплейс решений и партнёрская сеть."),
]
for i, (head, body) in enumerate(cells):
    P.point_item(s, head, body, (40 + i * 400, 220, 360, 360))
prs.save("tmp/probe_points.pptx")
print("saved")
```

Run: `python tmp/probe_points.py && python -m scripts.render_png tmp/probe_points.pptx tmp/png_probe`

- [ ] **Step 4: Visually verify.** Read `tmp/png_probe/probe_points_s1.png`. Confirm: green rule above each bold heading, clean modular rhythm, body text legible, matches `references/exemplars/points_3.png` rhythm. Adjust sizes/offsets in `point_item` and re-run until it matches.

- [ ] **Step 5: Commit**

```bash
git add renderers/designer/primitives.py
git commit -m "feat(designer): add divider_line + point_item brand primitives"
```

### Task 2: Colored table header row

**Files:**
- Modify: `renderers/designer/primitives.py` (`table_block`, ~line 556-638)

- [ ] **Step 1: Add a header-fill option.** Change the `table_block` signature to accept `header_fill` and tint the header row. Replace the header signature line:

```python
def table_block(slide, headers, rows, rect_px, accent_col=None,
                first_col_wider: bool = True, dark_bg: bool = False,
                header_fill: str = "green"):
```

- [ ] **Step 2: Apply the header fill.** Replace the header-cell loop (currently fills `None` = transparent, ~line 611-615) with:

```python
    HEADER_FILLS = {
        "green": (GREEN, GRAPHITE),       # green bg, graphite text (template p.52)
        "graphite": (GRAPHITE, WHITE),
        "none": (None, head_color),
    }
    hdr_bg, hdr_txt = HEADER_FILLS.get(header_fill, (GREEN, GRAPHITE))
    for c in range(n_cols):
        cell = table.cell(0, c)
        _tbl_cell_fill(cell, hdr_bg)
        _tbl_cell_margins(cell)
        _tbl_cell_text(cell, headers[c], body_pt, True, hdr_txt)
```

- [ ] **Step 3: Render a probe.** Create `tmp/probe_table.py`:

```python
from pptx import Presentation
from pptx.util import Emu
from renderers.designer import primitives as P
from worker import skill_bridge
skill_bridge.install()
prs = Presentation()
prs.slide_width = Emu(1280 * P.EMU_PER_PX); prs.slide_height = Emu(720 * P.EMU_PER_PX)
s = prs.slides.add_slide(prs.slide_layouts[6])
P.background(s, "white")
P.title_block(s, "Сравнение тарифов", (40, 40, 1000, 110))
headers = ["Параметр", "Базовый", "Бизнес", "Enterprise"]
rows = [["vCPU", "8", "32", "128"], ["RAM, ГБ", "16", "64", "256"],
        ["SLA", "99.5%", "99.9%", "99.95%"], ["Поддержка", "8/5", "24/7", "24/7 + TAM"]]
P.table_block(s, headers, rows, (40, 180, 1200, 460), accent_col=3)
prs.save("tmp/probe_table.pptx"); print("saved")
```

Run: `python tmp/probe_table.py && python -m scripts.render_png tmp/probe_table.pptx tmp/png_probe`

- [ ] **Step 4: Visually verify.** Read `tmp/png_probe/probe_table_s1.png`. Confirm: green header row with graphite text, zebra body, highlighted accent column, matches `references/exemplars/table_zebra.png`. Adjust and re-run until it matches.

- [ ] **Step 5: Commit**

```bash
git add renderers/designer/primitives.py
git commit -m "feat(designer): colored (green) table header row"
```

### Task 3: `display_title` (oversized cover heading)

**Files:**
- Modify: `renderers/designer/primitives.py`

- [ ] **Step 1: Add the primitive** (append after `title_block`, ~line 254):

```python
def display_title(slide, text: str, rect_px, *, dark_bg: bool = False,
                  max_pt: float = 96.0):
    """Oversized cover heading (template covers): SemiBold, shrink-to-fit up to
    max_pt, top-anchored so it fills the upper band. No accent underline (the
    cover's green fill / portal carries the brand)."""
    left, top, w, h = rect_px
    color = WHITE if dark_bg else GRAPHITE
    fit_pt, _, _ = _fit(text, w, h, base_pt=max_pt, min_pt=40.0,
                        semibold=True, wrap=True, balance=True)
    tb = slide.shapes.add_textbox(px(left), px(top), px(w), px(h))
    tf = tb.text_frame
    tf.word_wrap = True
    _zero_margins(tf)
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.name = SEMIBOLD_FONT
    r.font.size = Pt(fit_pt)
    r.font.color.rgb = color
    return tb
```

- [ ] **Step 2: Render a probe** (green cover). Create `tmp/probe_cover.py`:

```python
from pptx import Presentation
from pptx.util import Emu
from renderers.designer import primitives as P
from worker import skill_bridge
skill_bridge.install()
prs = Presentation()
prs.slide_width = Emu(1280 * P.EMU_PER_PX); prs.slide_height = Emu(720 * P.EMU_PER_PX)
s = prs.slides.add_slide(prs.slide_layouts[6])
P.background(s, "green")
P.portal(s, (980, 520, 150), n=4)
P.display_title(s, "Облачная платформа Cloud.ru", (60, 120, 900, 360), dark_bg=False)
prs.save("tmp/probe_cover.pptx"); print("saved")
```

Run: `python tmp/probe_cover.py && python -m scripts.render_png tmp/probe_cover.pptx tmp/png_probe`

- [ ] **Step 3: Visually verify.** Read `tmp/png_probe/probe_cover_s1.png` against `references/exemplars/cover_green.png`. Confirm giant title + portal staircase on green fill. Adjust portal placement / title color (graphite vs white on green) and re-run until it reads as a Cloud.ru cover.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/primitives.py
git commit -m "feat(designer): add display_title cover primitive"
```

---

## Phase 2 — Archetype skeletons (renderers/designer/layouts.py)

Each skeleton is a function that receives the slide + a content dict and lays out brand-dressed zones deterministically. This replaces blind grid placement.

### Task 4: Layouts module scaffold + `cover_green`

**Files:**
- Create: `renderers/designer/layouts.py`

- [ ] **Step 1: Scaffold + first skeleton**

```python
"""Archetype layout skeletons for the designer skill.

Each skeleton owns its slide's layout: it places brand-dressed zones at fixed
coordinates and fills them from a content dict. The composer chooses an
archetype + supplies CONTENT (not coordinates); these functions render it so
output matches the Cloud.ru reference instead of a blind grid raffle.

A skeleton signature is always (slide, content: dict, *, dark: bool) -> None.
content keys are archetype-specific and documented per function.
"""
from __future__ import annotations

from renderers.designer import primitives as P

CANVAS_W, CANVAS_H = 1280, 720
M = 60  # cover/section outer margin


def cover_green(slide, content, *, dark=False):
    """Full green fill + portal staircase + display title (+ optional subtitle).

    content: {"title": str, "subtitle": str?}
    """
    P.background(slide, "green")
    P.portal(slide, (980, 520, 150), n=4)
    P.display_title(slide, content.get("title") or "", (M, 130, 860, 320))
    sub = (content.get("subtitle") or "").strip()
    if sub:
        P.body_block(slide, [sub], (M, 470, 760, 120))
```

- [ ] **Step 2: Render via probe.** Create `tmp/probe_layout.py` (reused for all skeletons):

```python
import sys
from pptx import Presentation
from pptx.util import Emu
from renderers.designer import primitives as P
from renderers.designer import layouts as L
from worker import skill_bridge
skill_bridge.install()

def render(fn_name, content, dark=False):
    prs = Presentation()
    prs.slide_width = Emu(1280 * P.EMU_PER_PX); prs.slide_height = Emu(720 * P.EMU_PER_PX)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    getattr(L, fn_name)(s, content, dark=dark)
    out = f"tmp/probe_{fn_name}.pptx"
    prs.save(out); print(out)

if __name__ == "__main__":
    render("cover_green", {"title": "Облачная платформа Cloud.ru",
                           "subtitle": "Инфраструктура нового поколения"})
```

Run: `python tmp/probe_layout.py && python -m scripts.render_png tmp/probe_cover_green.pptx tmp/png_probe`

- [ ] **Step 3: Visually verify** `tmp/png_probe/probe_cover_green_s1.png` vs `references/exemplars/cover_green.png`. Adjust until it matches.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/layouts.py tmp/probe_layout.py
git commit -m "feat(designer): layouts module + cover_green skeleton"
```

### Task 5: `points_3` / `points_4` / `points_6` / `points_8` skeletons

**Files:**
- Modify: `renderers/designer/layouts.py`

- [ ] **Step 1: Add a shared points grid.** Append:

```python
def _points_grid(slide, content, cols, rows, *, dark=False):
    """Title band + a cols×rows grid of point_item modules (green divider +
    bold head + body). content: {"title": str, "points": [{"head","text"}...]}.
    Fills row-major; ignores extra points beyond cols*rows.
    """
    P.background(slide, "graphite" if dark else "white")
    P.title_block(slide, content.get("title") or "", (40, 40, 1100, 110),
                  dark_bg=dark)
    pts = (content.get("points") or [])[: cols * rows]
    area_top, area_h = 200, CANVAS_H - 200 - 60
    gap = 24
    cell_w = (CANVAS_W - 2 * 40 - gap * (cols - 1)) / cols
    cell_h = (area_h - gap * (rows - 1)) / rows
    for i, pt in enumerate(pts):
        r, c = divmod(i, cols)
        left = 40 + c * (cell_w + gap)
        top = area_top + r * (cell_h + gap)
        P.point_item(slide, pt.get("head") or "", pt.get("text") or "",
                     (left, top, cell_w, cell_h), dark_bg=dark)


def points_3(slide, content, *, dark=False):
    _points_grid(slide, content, cols=3, rows=1, dark=dark)


def points_4(slide, content, *, dark=False):
    _points_grid(slide, content, cols=2, rows=2, dark=dark)


def points_6(slide, content, *, dark=False):
    _points_grid(slide, content, cols=3, rows=2, dark=dark)


def points_8(slide, content, *, dark=False):
    _points_grid(slide, content, cols=4, rows=2, dark=dark)
```

- [ ] **Step 2: Render each.** Add to `tmp/probe_layout.py`'s `__main__` (run one at a time):

```python
    pts = [{"head": f"Пункт {i}", "text": "Краткое описание направления и его ценности."}
           for i in range(1, 9)]
    render("points_3", {"title": "Три направления", "points": pts[:3]})
    render("points_4", {"title": "Четыре опоры", "points": pts[:4]})
    render("points_6", {"title": "Шесть возможностей", "points": pts[:6]})
    render("points_8", {"title": "Восемь сервисов", "points": pts[:8]})
```

Run each through `scripts.render_png`.

- [ ] **Step 3: Visually verify** each PNG vs `references/exemplars/points_*.png`. Confirm even rhythm, no text clipping at 6/8 density, green dividers aligned. Tune `area_top`, `gap`, font bases in `point_item` until clean at all densities.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/layouts.py tmp/probe_layout.py
git commit -m "feat(designer): points_3/4/6/8 skeletons with green dividers"
```

### Task 6: `bullet_list`, `section_divider`, `cover_dark` skeletons

**Files:**
- Modify: `renderers/designer/layouts.py`

- [ ] **Step 1: Add them**

```python
def bullet_list(slide, content, *, dark=False):
    """Workhorse: title + left intro (optional) + green-tick bullet column.
    content: {"title": str, "intro": str?, "bullets": [str,...]}
    """
    P.background(slide, "graphite" if dark else "white")
    P.title_block(slide, content.get("title") or "", (40, 40, 1100, 110),
                  dark_bg=dark)
    intro = (content.get("intro") or "").strip()
    top = 200
    if intro:
        P.body_block(slide, [intro], (40, top, 1160, 70), size_pt=18, dark_bg=dark)
        top += 90
    P.body_block(slide, content.get("bullets") or [], (40, top, 1160, CANVAS_H - top - 60),
                 size_pt=18, dark_bg=dark)


def section_divider(slide, content, *, dark=True):
    """Section break: dark fill + portal + large section title + kicker.
    content: {"title": str, "kicker": str?}
    """
    P.background(slide, "graphite" if dark else "white")
    P.portal(slide, (60, 560, 130), n=3, dark_bg=dark)
    kicker = (content.get("kicker") or "").strip()
    if kicker:
        P.body_block(slide, [kicker.upper()], (60, 230, 700, 60), size_pt=16, dark_bg=dark)
    P.display_title(slide, content.get("title") or "", (60, 290, 1000, 300),
                    dark_bg=dark, max_pt=80)


def cover_dark(slide, content, *, dark=True):
    """Dark cover: graphite fill, green outline title plate area, display title,
    descriptor line. content: {"title": str, "subtitle": str?}
    """
    P.background(slide, "graphite")
    P.portal(slide, (980, 520, 150), n=4, dark_bg=True)
    P.divider_line(slide, 60, 150, 80)
    P.display_title(slide, content.get("title") or "", (60, 180, 900, 320), dark_bg=True)
    sub = (content.get("subtitle") or "").strip()
    if sub:
        P.body_block(slide, [sub], (60, 520, 760, 120), dark_bg=True)
```

- [ ] **Step 2-3: Render + visually verify** each via the probe (mirror Task 5 pattern). Compare `bullet_list` to `references/exemplars/bullet_list.png`, `section_divider`/`cover_dark` to `references/exemplars/cover_dark.png`. Tune until they match.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/layouts.py tmp/probe_layout.py
git commit -m "feat(designer): bullet_list, section_divider, cover_dark skeletons"
```

### Task 7: `table_zebra`, `chart_columns`, `roadmap_timeline` skeletons

**Files:**
- Modify: `renderers/designer/layouts.py`

- [ ] **Step 1: Add them** (these wrap the existing rich primitives with a title band + standard zone):

```python
def table_zebra(slide, content, *, dark=False):
    """Title + full-width branded zebra table.
    content: {"title": str, "headers": [str], "rows": [[str]], "accent_col": int?}
    """
    P.background(slide, "graphite" if dark else "white")
    P.title_block(slide, content.get("title") or "", (40, 40, 1100, 100), dark_bg=dark)
    P.table_block(slide, content.get("headers") or [], content.get("rows") or [],
                  (40, 170, 1200, CANVAS_H - 170 - 60),
                  accent_col=content.get("accent_col"), dark_bg=dark)


def chart_columns(slide, content, *, dark=False):
    """Title + clustered column chart (5-color brand ramp).
    content: {"title": str, "categories": [str], "series": [{"name","values"}],
              "accent_idx": int?, "data_provenance": str?}
    """
    P.background(slide, "graphite" if dark else "white")
    P.title_block(slide, content.get("title") or "", (40, 40, 1100, 100), dark_bg=dark)
    P.chart_block(slide, "bar", content.get("categories") or [],
                  content.get("series") or [], (40, 170, 1200, CANVAS_H - 170 - 60),
                  accent_idx=content.get("accent_idx", 0),
                  data_provenance=content.get("data_provenance", "native"), dark_bg=dark)


def roadmap_timeline(slide, content, *, dark=False):
    """Title + horizontal axis + evenly-spaced milestone ticks.
    content: {"title": str, "milestones": [{"label","text","accent"?}]}
    """
    P.background(slide, "graphite" if dark else "white")
    P.title_block(slide, content.get("title") or "", (40, 40, 1100, 100), dark_bg=dark)
    ms = content.get("milestones") or []
    axis_y = 380
    P.timeline_axis(slide, axis_y, 60, 1220, dark_bg=dark)
    if ms:
        n = len(ms)
        span = (1220 - 60) / max(1, n)
        for i, m in enumerate(ms):
            left = 60 + i * span + 10
            P.milestone_tick(slide, m.get("label") or "", m.get("text") or "",
                             (left, axis_y - 150, span - 20, 130),
                             accent=bool(m.get("accent")), dark_bg=dark)
```

- [ ] **Step 2-3: Render + visually verify** each vs `references/exemplars/{table_zebra,chart_columns,roadmap_timeline}.png`. Tune zones/spacing until they match.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/layouts.py tmp/probe_layout.py
git commit -m "feat(designer): table_zebra, chart_columns, roadmap_timeline skeletons"
```

---

## Phase 3 — Wire skeletons into the pipeline

Route composition through skeletons. Composer now emits a `layout` name + zone content; assembler dispatches to `layouts.py`. Keep the legacy free-grid path as fallback so nothing breaks mid-migration.

### Task 8: Add `layout` + `content` to the Composition DSL

**Files:**
- Modify: `renderers/designer/composition_dsl.py`
- Read first: the full file (to match existing field/validator style).

- [ ] **Step 1: Read** `renderers/designer/composition_dsl.py` to learn the `Composition` model shape.

- [ ] **Step 2: Add optional skeleton fields** to `Composition` (additive, defaults keep legacy path working):

```python
    # Archetype-skeleton path (Phase 3 redesign). When `layout` is set the
    # assembler renders via renderers.designer.layouts.<layout>(slide, content)
    # and IGNORES `blocks`. When None, the legacy free-grid `blocks` path runs.
    layout: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)
```

(Ensure `Any`/`Field` are imported.)

- [ ] **Step 3: Verify import** — `python -c "from renderers.designer.composition_dsl import Composition; print(Composition(slide_num=1, layout='cover_green', content={'title':'x'}))"`. Expected: prints a model instance, no error.

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/composition_dsl.py
git commit -m "feat(designer): add layout+content skeleton fields to Composition DSL"
```

### Task 9: Assembler dispatches to skeletons

**Files:**
- Modify: `renderers/designer/native_assembler.py` (`assemble_slide`, ~line 316)

- [ ] **Step 1: Add a skeleton dispatch** at the top of `assemble_slide`, before the legacy de-overlap path:

```python
from renderers.designer import layouts as L

_LAYOUTS = {
    name: getattr(L, name) for name in (
        "cover_green", "cover_dark", "section_divider",
        "points_3", "points_4", "points_6", "points_8", "bullet_list",
        "table_zebra", "chart_columns", "roadmap_timeline",
    )
}
```

Then in `assemble_slide`, immediately after `slide = prs.slides.add_slide(blank)` and computing `dark`:

```python
    if comp.layout and comp.layout in _LAYOUTS:
        _LAYOUTS[comp.layout](slide, comp.content, dark=dark)
        return
```

(`cover_photo` is intentionally out of scope — no raster.)

- [ ] **Step 2: Re-assemble an existing comp dump with a hand-edited layout.** Create `tmp/probe_skeleton_deck.py` that builds 3 Compositions using `layout`+`content` (one cover_green, one points_3, one table_zebra) and calls `build_deck` to `tmp/probe_skeleton.pptx`.

```python
from renderers.designer.composition_dsl import Composition
from renderers.designer.native_assembler import build_deck
from worker import skill_bridge
skill_bridge.install()
comps = [
    Composition(slide_num=1, layout="cover_green",
                content={"title": "Облачная платформа Cloud.ru",
                         "subtitle": "Инфраструктура нового поколения"}),
    Composition(slide_num=2, layout="points_3",
                content={"title": "Три направления",
                         "points": [{"head": "Инфраструктура", "text": "Вычисления и хранение."},
                                    {"head": "Платформа", "text": "Управляемые сервисы."},
                                    {"head": "Экосистема", "text": "Маркетплейс решений."}]}),
    Composition(slide_num=3, layout="table_zebra",
                content={"title": "Тарифы", "accent_col": 3,
                         "headers": ["Параметр", "Базовый", "Бизнес", "Enterprise"],
                         "rows": [["vCPU", "8", "32", "128"], ["SLA", "99.5%", "99.9%", "99.95%"]]}),
]
build_deck(comps, "tmp/probe_skeleton.pptx"); print("saved")
```

Run: `python tmp/probe_skeleton_deck.py && python -m scripts.render_png tmp/probe_skeleton.pptx tmp/png_probe`

- [ ] **Step 3: Visually verify** all 3 PNGs render via the skeleton path and match their exemplars. Confirm the legacy path still works by re-running `scripts.reassemble_design` on an old `_comp.json` (no `layout` field → free-grid path, must still render).

- [ ] **Step 4: Commit**

```bash
git add renderers/designer/native_assembler.py tmp/probe_skeleton_deck.py
git commit -m "feat(designer): assembler dispatches Composition.layout to skeletons"
```

### Task 10: Composer emits skeleton layout + content

**Files:**
- Modify: `llm/prompts/designer/slide_composer.py`
- Modify: `graph/designer/planner.py` (map archetypes → skeleton names)
- Read first: `llm/prompts/designer/slide_composer.py` and `llm/prompts/designer/__init__.py`.

- [ ] **Step 1: Read** the current `slide_composer` prompt builder to learn its message shape and how `archetype` is passed.

- [ ] **Step 2: Map planner archetypes → skeleton names.** In `planner.py`, add a translation used by the composer call (keep `archetype_for` returning its current vocabulary; add a mapper):

```python
# Planner archetype -> layout skeleton name (renderers.designer.layouts).
ARCHETYPE_TO_LAYOUT = {
    "cover": "cover_green",
    "section-divider": "section_divider",
    "table": "table_zebra",
    "data-chart": "chart_columns",
    "timeline": "roadmap_timeline",
    "title-body": "bullet_list",
    # points_N chosen by the composer from bullet count; default bullet_list.
}


def layout_for(archetype: str, n_points: int = 0) -> str:
    if archetype == "title-body" and 3 <= n_points <= 8:
        return {3: "points_3", 4: "points_4", 6: "points_6", 8: "points_8"}.get(
            n_points, "points_6" if n_points > 4 else "points_4")
    return ARCHETYPE_TO_LAYOUT.get(archetype, "bullet_list")
```

- [ ] **Step 3: Rewrite the composer prompt** to emit `{layout, content}` for the chosen skeleton instead of free `blocks`. The prompt must:
  - State the chosen `layout` name and its required `content` keys (documented per skeleton in `layouts.py`).
  - Pass source text verbatim (text-is-sacred), only re-chunking into the skeleton's zones (e.g. split body into `points[].head`/`text`).
  - Include the brand-exemplar PNG of that layout as a vision few-shot (wired in Task 13).

Write the new `build_messages(stub, content, layout, exemplar_png=None)` accordingly (exact prose in the prompt file). Update `_compose_one` in `nodes.py` to validate against `Composition` with the `layout`/`content` fields and to choose the layout via `layout_for`.

- [ ] **Step 4: Visually verify via a real run** (deferred to Phase 5 e2e). For now, run an offline smoke: feed a saved brief/classification through `compose_node` with a stubbed LLM returning a known `{layout, content}` and assemble. Render + inspect.

- [ ] **Step 5: Commit**

```bash
git add llm/prompts/designer/slide_composer.py graph/designer/planner.py graph/designer/nodes.py
git commit -m "feat(designer): composer emits skeleton layout+content"
```

---

## Phase 4 — Vision integration

Kimi-K2.6 is the only multimodal model. Use `llm/client.py build_vision_content(prompt, images)` to attach PNGs.

### Task 11: Vision input at classify (point 1)

**Files:**
- Modify: `graph/designer/nodes.py` (add a vision-augment to archetype choice) OR `graph/designer/planner.py`
- Read first: `graph/nodes/agents.py` `classify_node` (to learn where source-slide PNGs live in artefacts) and `llm/client.py build_vision_content`.

- [ ] **Step 1: Locate source PNGs.** Read `classify_node` / `parse_node` to find the artefact key holding per-slide source PNG paths (brief_parser already consumes them).

- [ ] **Step 2: Add a vision archetype-hint pass.** Add a node helper that, per slide, sends the source PNG + the archetype shortlist to Kimi (reuse `PIXEL_JUDGE` role or add `INPUT_VISION`) and returns a refined archetype + a one-line "visual intent" note merged into the composer content. Keep it cheap: 1 call/slide, skip if no PNG.

- [ ] **Step 3: Visually verify** on one real deck (Phase 5): confirm slides where the source had an obvious structure (e.g. a table) now pick the matching skeleton more often than the text-only classifier did. Compare before/after PNGs.

- [ ] **Step 4: Commit**

```bash
git add graph/designer/nodes.py graph/designer/planner.py llm/roles.py
git commit -m "feat(designer): vision-on-input refines archetype choice at classify"
```

### Task 12: Vision-QA self-correction loop (point 3)

**Files:**
- Modify: `graph/designer/nodes.py` (new `vision_qa_node` after assemble) and `graph/designer/graph.py` (wire the loop)
- Create: `llm/prompts/designer/pixel_judge.py`

- [ ] **Step 1: Add a single-slide render helper** the node can call in-process (reuse `scripts/render_png.pptx_to_pdf`/`pdf_to_pngs`), rendering only the just-built deck to PNGs in a temp dir.

- [ ] **Step 2: Write the `pixel_judge` prompt.** Input: the rendered slide PNG + its `{layout, content}` + the archetype exemplar PNG. Output (Pydantic `PixelVerdict`): `verdict` READY/FIX, `issues: [str]` (overlap/void/clipping/off-brand), optional `content_patch: dict` (targeted edits to `content`, e.g. shorten an overflowing head).

- [ ] **Step 3: Wire the loop.** After `native_assemble`, render each slide → `PIXEL_JUDGE`. If FIX and passes < 2: apply `content_patch` (or re-call composer with the issues) → re-assemble that slide → re-judge. Cap 2 passes/slide. Persist the final PNGs.

- [ ] **Step 4: Visually verify** on a real deck: pick 2-3 slides the judge flagged, confirm the post-fix PNG actually resolves the issue (no new regressions). This is the heart of "designer looks at their own work."

- [ ] **Step 5: Commit**

```bash
git add graph/designer/nodes.py graph/designer/graph.py llm/prompts/designer/pixel_judge.py llm/roles.py
git commit -m "feat(designer): vision-QA render->critique->fix loop (<=2 passes)"
```

### Task 13: Vision reference few-shot at compose (point 2)

**Files:**
- Modify: `llm/prompts/designer/slide_composer.py`, `graph/designer/nodes.py`

- [ ] **Step 1: Load the exemplar.** In `_compose_one`, resolve `skill_assets/brand/references/exemplars/<layout>.png` and pass it to `slide_composer.build_messages(..., exemplar_png=path)` via `build_vision_content`. NOTE: composer is GLM (text-only) — so route the exemplar to a Kimi "layout planner" pre-step OR switch the composer call to Kimi for slides where the exemplar matters. Decide by a quick A/B (Step 2).

- [ ] **Step 2: A/B visually.** Compose 3 representative slides (points_3, table_zebra, chart_columns) with vs without the exemplar few-shot; render both; compare PNGs to the exemplar. Keep whichever is closer to brand. Record the verdict in the spec.

- [ ] **Step 3: Commit**

```bash
git add llm/prompts/designer/slide_composer.py graph/designer/nodes.py
git commit -m "feat(designer): brand exemplar vision few-shot at compose"
```

### Task 14: Deck-level vision review (point 4)

**Files:**
- Modify: `graph/designer/nodes.py` (new `deck_review_node`), `graph/designer/graph.py`
- Create: `llm/prompts/designer/deck_review.py`

- [ ] **Step 1: Write the prompt.** Input: all slide PNGs (or a contact-sheet montage) → `VISUAL_VERIFIER`. Output `DeckVerdict`: per-slide flags for rhythm breaks, duplicate layouts, missing cover/divider, color imbalance, plus deck-level notes.

- [ ] **Step 2: Wire as the final node** after the QA loop. For now it REPORTS (logs + persists verdict); auto-fix is out of scope (avoid an unbounded loop). Severe flags can trigger one targeted re-compose of the named slide.

- [ ] **Step 3: Visually verify** on a real deck: confirm the verdict matches what you see (e.g. it catches two adjacent identical layouts).

- [ ] **Step 4: Commit**

```bash
git add graph/designer/nodes.py graph/designer/graph.py llm/prompts/designer/deck_review.py
git commit -m "feat(designer): deck-level vision consistency review"
```

---

## Phase 5 — End-to-end live validation (the acceptance gate)

### Task 15: Full live run on all 5 test decks, slide-by-slide visual acceptance

**Files:**
- Use: `scripts/live_run_design.py`, `scripts/render_png.py`
- Read first: prior validation memories for the 5 canonical test decks' input paths.

- [ ] **Step 1: Run each deck live.** For each of the 5 test decks: `python -m scripts.live_run_design <deck.pptx>` (real Cloud.ru — authorized). Capture the built `.pptx` + the persisted `_comp.json`.

- [ ] **Step 2: Render every slide.** `python -m scripts.render_png <built>.pptx tmp/accept/<deck>` for each.

- [ ] **Step 3: Slide-by-slide visual acceptance.** Read EVERY emitted PNG. For each slide confirm against the brand reference: correct archetype, branded dressing (green dividers / colored headers / portal covers), no overlap/void/clipping, consistent rhythm. Log every defect with slide number + screenshot.

- [ ] **Step 4: Fix-and-reverify loop.** For each defect: fix at the right layer (primitive / skeleton / prompt), re-run (reassemble offline when deterministic, live when LLM-driven), re-render, re-inspect. Iterate until all 5 decks pass slide-by-slide.

- [ ] **Step 5: Final commit + memory.**

```bash
git add -A
git commit -m "feat(designer): visual redesign validated e2e on 5 decks"
```

Then save a memory entry summarizing what was surprising/non-obvious in the validation (per auto-memory rules), and update the spec status to "validated".

---

## Self-Review (completed by plan author)

**Spec coverage:** Cause 1 (brand vocabulary) → Tasks 1-3 + Phase 2. Cause 2 (blind grid) → Phase 2 skeletons + Task 9. Cause 3 (no archetype templates) → Phase 2 + Task 10. Cause 4 (no visual QA) → Task 12. Vision points 1-4 → Tasks 11/13/12/14. Validation mandate → harness Task 0 + per-task render-inspect + Phase 5. ✓

**Placeholder scan:** Pixel coordinates in skeletons are explicit starting values, refined by the mandated render-inspect loop — this is intentional per the user's "validate visually" directive, not a TODO. Prompt prose for Tasks 10/12/13/14 is described by required inputs/outputs rather than fully written, because exact wording must be tuned against live model behavior; each has a concrete Pydantic output contract. ✓

**Type consistency:** `Composition.layout: str|None` + `Composition.content: dict` used identically in Tasks 8/9/10. Skeleton signature `(slide, content, *, dark)` consistent across Phase 2 and the `_LAYOUTS` dispatch (Task 9). `layout_for`/`ARCHETYPE_TO_LAYOUT` names consistent between Tasks 9 and 10. ✓
