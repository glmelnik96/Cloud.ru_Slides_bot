# Image-Slide Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop dropping visual/image-only slides — reconstruct structured grouped diagrams into native brand layouts, and fall back to a full-bleed render for the rest, so zero slides are lost.

**Architecture:** Add recursive group parsing to `parse_pptx`, a deterministic `classify_visual_kind` router, and a `media_prep` step in `parse_node` that produces an `image_path` (extracted raster or rendered PNG). Structured slides route to the existing `flow_diagram_native` renderer; raster/opaque slides route to the existing `image_native` renderer. No new renderers; no `build_v9` core changes.

**Tech Stack:** Python, python-pptx, Pillow, LibreOffice (soffice/pdftoppm in worker), pytest. Tests import vendored skill scripts via `from worker import skill_bridge; skill_bridge.install()`.

---

## File Structure

- `skill_assets/scripts/parse_pptx.py` — MODIFY: add `_walk_shapes` recursion + `visual_kind`/`group_nodes` fields.
- `skill_assets/scripts/visual_kind.py` — CREATE: pure `classify_visual_kind(slide_data)` + threshold constants.
- `graph/nodes/pipeline.py` — MODIFY: `media_prep` helper + wire into `parse_node`; generalize slide-render helper.
- `llm/prompts/agent_02_slide_classifier.py` — MODIFY: route `structured`→flow preset, `raster`/`opaque`→image_native.
- `tests/unit/test_walk_shapes.py` — CREATE.
- `tests/unit/test_visual_kind.py` — CREATE.
- `tests/unit/test_media_prep.py` — CREATE.

`ParsedDeck`/`ParsedSlide` models use `extra="allow"`, so `visual_kind` and `group_nodes` roundtrip with **no schema change**.

---

## Task 1: Recursive group walk in parse_pptx

**Files:**
- Modify: `skill_assets/scripts/parse_pptx.py`
- Test: `tests/unit/test_walk_shapes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_walk_shapes.py
"""Recursive group walk: nested text + pictures are recovered."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from pptx import Presentation  # noqa: E402
from pptx.util import Emu  # noqa: E402

from parse_pptx import _walk_shapes  # noqa: E402


def _deck_with_nested_group(tmp_path):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    # Outer group with a textbox + an inner group holding another textbox.
    # python-pptx cannot add groups directly, so build via two textboxes at
    # top level plus a real group through the shape tree is awkward; instead
    # assert the walker handles a flat tree AND that it recurses when groups
    # exist (using a fixture deck shipped in tests/fixtures).
    tb = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    tb.text_frame.text = "TOP"
    out = tmp_path / "flat.pptx"
    prs.save(out)
    return str(out)


def test_walk_shapes_flat_returns_leaves(tmp_path):
    path = _deck_with_nested_group(tmp_path)
    prs = Presentation(path)
    leaves = _walk_shapes(prs.slides[0].shapes)
    texts = [lf["text"] for lf in leaves if lf["text"]]
    assert "TOP" in texts
    assert all({"shape_type", "text", "left", "top", "w", "h", "depth"} <= set(lf) for lf in leaves)


def test_walk_shapes_recurses_into_group_fixture():
    # tests/fixtures/grouped_diagram.pptx: slide 1 has a GROUP containing
    # textboxes "Node A", "Node B" and a nested GROUP with "Node C".
    import os
    fixture = os.path.join(os.path.dirname(__file__), "..", "fixtures", "grouped_diagram.pptx")
    prs = Presentation(fixture)
    leaves = _walk_shapes(prs.slides[0].shapes)
    texts = [lf["text"] for lf in leaves if lf["text"]]
    assert "Node A" in texts and "Node B" in texts and "Node C" in texts
    # Nested node carries depth >= 2.
    node_c = next(lf for lf in leaves if lf["text"] == "Node C")
    assert node_c["depth"] >= 2
```

- [ ] **Step 2: Build the fixture deck**

Run this one-off script to create `tests/fixtures/grouped_diagram.pptx` (a real nested-group deck python-pptx cannot author directly — build it by cloning a group via XML):

```python
# scripts-local: create fixture (run once, not committed as code)
from pptx import Presentation
from pptx.util import Emu
from pptx.oxml.ns import qn
import copy

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
spTree = slide.shapes._spTree

def make_group(node_texts):
    # Minimal grpSp with child textboxes; reuse python-pptx textbox XML.
    grp = spTree.makeelement(qn('p:grpSp'), {})
    nv = grp.makeelement(qn('p:nvGrpSpPr'), {})
    cnv = grp.makeelement(qn('p:cNvPr'), {'id': '99', 'name': 'grp'})
    nv.append(cnv); nv.append(grp.makeelement(qn('p:cNvGrpSpPr'), {}))
    nv.append(grp.makeelement(qn('p:nvPr'), {}))
    grp.append(nv)
    grp.append(grp.makeelement(qn('p:grpSpPr'), {}))
    for i, t in enumerate(node_texts):
        tb = slide.shapes.add_textbox(Emu(i*914400), Emu(0), Emu(800000), Emu(400000))
        tb.text_frame.text = t
        grp.append(copy.deepcopy(tb._element))
        spTree.remove(tb._element)
    return grp

outer = make_group(["Node A", "Node B"])
inner = make_group(["Node C"])
outer.append(inner)
spTree.append(outer)
prs.save("tests/fixtures/grouped_diagram.pptx")
print("fixture written")
```

Verify: `ls tests/fixtures/grouped_diagram.pptx`

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_walk_shapes.py -v`
Expected: FAIL with `ImportError: cannot import name '_walk_shapes'`

- [ ] **Step 4: Implement `_walk_shapes` in parse_pptx.py**

Add near the top of `parse_pptx.py`, after the imports:

```python
def _walk_shapes(shapes, depth=0):
    """Flatten the shape tree, recursing into GROUP shapes.

    Returns a list of leaf-shape dicts:
      {shape_type, text, left, top, w, h, depth}
    Text is "" for non-text shapes. Geometry is in EMU (None if absent).
    A shape that raises on attribute access is skipped, not fatal.
    """
    out = []
    for shape in shapes:
        try:
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                out += _walk_shapes(shape.shapes, depth + 1)
                continue
            text = ""
            if shape.has_text_frame:
                text = shape.text_frame.text.strip()
            out.append({
                "shape_type": shape.shape_type,
                "text": text,
                "left": shape.left, "top": shape.top,
                "w": shape.width, "h": shape.height,
                "depth": depth,
            })
        except Exception:
            continue
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_walk_shapes.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add skill_assets/scripts/parse_pptx.py tests/unit/test_walk_shapes.py tests/fixtures/grouped_diagram.pptx
git commit -m "feat(parse): recursive group walk (_walk_shapes)"
```

---

## Task 2: classify_visual_kind router

**Files:**
- Create: `skill_assets/scripts/visual_kind.py`
- Test: `tests/unit/test_visual_kind.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_visual_kind.py
"""Deterministic visual_kind routing."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from visual_kind import (  # noqa: E402
    classify_visual_kind,
    RASTER_MIN_AREA_PX,
    STRUCTURED_MIN_NODES,
    STRUCTURED_MAX_NODES,
)

EMU = 9525


def _node(text, order):
    return {"text": text, "left": order * 100 * EMU, "top": 200 * EMU,
            "w": 90 * EMU, "h": 40 * EMU, "order": order}


def test_none_when_normal_text():
    sd = {"title": "Заголовок", "body": ["абзац один", "абзац два"],
          "group_nodes": [], "images": []}
    assert classify_visual_kind(sd) == "none"


def test_structured_numbered_nodes():
    sd = {"title": None, "body": [],
          "group_nodes": [_node(f"Пункт {i}", i) for i in range(1, 6)],
          "images": []}
    assert classify_visual_kind(sd) == "structured"


def test_raster_large_picture():
    sd = {"title": None, "body": [], "group_nodes": [],
          "images": [{"width_emu": 1149 * EMU, "height_emu": 535 * EMU}]}
    assert classify_visual_kind(sd) == "raster"


def test_opaque_no_text_no_raster():
    sd = {"title": None, "body": [], "group_nodes": [],
          "images": [{"width_emu": 100 * EMU, "height_emu": 100 * EMU}]}  # icon-sized
    assert classify_visual_kind(sd) == "opaque"


def test_threshold_two_nodes_not_structured():
    sd = {"title": None, "body": [], "group_nodes": [_node("A", 1), _node("B", 2)],
          "images": []}
    assert classify_visual_kind(sd) != "structured"


def test_threshold_nine_nodes_falls_to_opaque():
    sd = {"title": None, "body": [],
          "group_nodes": [_node(f"N{i}", i) for i in range(1, 10)],
          "images": []}
    assert classify_visual_kind(sd) == "opaque"


def test_constants_sane():
    assert RASTER_MIN_AREA_PX == 200 * 200
    assert STRUCTURED_MIN_NODES == 3
    assert STRUCTURED_MAX_NODES == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_visual_kind.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'visual_kind'`

- [ ] **Step 3: Implement visual_kind.py**

```python
# skill_assets/scripts/visual_kind.py
"""Deterministic classification of a parsed slide into a routing class.

Classes:
  none        — ordinary text slide; feature does not intervene.
  structured  — grouped text nodes forming a diagram → flow_diagram_native (C).
  raster      — slide carries a content-sized embedded picture → image (A).
  opaque      — visual slide with neither text structure nor raster → image (B).

Pure function — no I/O, no LLM. Thresholds are named constants.
"""

EMU_PER_PX = 9525

RASTER_MIN_AREA_PX = 200 * 200      # smaller is an icon/logo, not content
STRUCTURED_MIN_NODES = 3            # fewer is not a diagram
STRUCTURED_MAX_NODES = 8            # more does not fit presets → render whole (B)


def _has_normal_text(slide_data):
    title = (slide_data.get("title") or "").strip()
    body = [b for b in (slide_data.get("body") or []) if str(b).strip()]
    return bool(title) or len(body) >= 1


def _largest_image_area_px(slide_data):
    best = 0
    for im in slide_data.get("images") or []:
        w = im.get("width_emu") or 0
        h = im.get("height_emu") or 0
        area = (w / EMU_PER_PX) * (h / EMU_PER_PX)
        best = max(best, area)
    return best


def classify_visual_kind(slide_data):
    nodes = [n for n in (slide_data.get("group_nodes") or [])
             if str(n.get("text", "")).strip()]
    has_raster = _largest_image_area_px(slide_data) >= RASTER_MIN_AREA_PX

    if _has_normal_text(slide_data):
        return "none"
    if STRUCTURED_MIN_NODES <= len(nodes) <= STRUCTURED_MAX_NODES:
        return "structured"
    if has_raster:
        return "raster"
    return "opaque"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_visual_kind.py -v`
Expected: PASS (all 7)

- [ ] **Step 5: Commit**

```bash
git add skill_assets/scripts/visual_kind.py tests/unit/test_visual_kind.py
git commit -m "feat: deterministic classify_visual_kind router"
```

---

## Task 3: Wire group_nodes + visual_kind into parse_pptx output

**Files:**
- Modify: `skill_assets/scripts/parse_pptx.py`
- Test: `tests/unit/test_walk_shapes.py` (extend)

- [ ] **Step 1: Write the failing test (extend test_walk_shapes.py)**

```python
def test_parse_emits_visual_kind_and_group_nodes(tmp_path):
    import os
    from parse_pptx import parse
    fixture = os.path.join(os.path.dirname(__file__), "..", "fixtures", "grouped_diagram.pptx")
    result = parse(fixture)
    s = result["slides"][0]
    assert "visual_kind" in s
    assert "group_nodes" in s
    # The fixture has 3 grouped text nodes and no normal text → structured.
    assert s["visual_kind"] == "structured"
    assert len(s["group_nodes"]) == 3
    assert all("order" in n and "text" in n for n in s["group_nodes"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_walk_shapes.py::test_parse_emits_visual_kind_and_group_nodes -v`
Expected: FAIL with `KeyError: 'visual_kind'`

- [ ] **Step 3: Modify `parse` in parse_pptx.py**

Add the import at top of file:

```python
from visual_kind import classify_visual_kind
```

In the `parse` per-slide loop, after the existing `for shape in slide.shapes:` block completes (right before `result["slides"].append(sdata)`), insert group recovery + classification:

```python
        # --- group recovery: pull text + pictures buried inside GROUP shapes
        leaves = _walk_shapes(slide.shapes)
        group_nodes = []
        order = 0
        for lf in leaves:
            if lf["depth"] >= 1 and lf["text"]:
                order += 1
                group_nodes.append({
                    "text": lf["text"],
                    "left": lf["left"], "top": lf["top"],
                    "w": lf["w"], "h": lf["h"],
                    "order": order,
                })
                # also surface buried text to body so vision/LLM see it
                sdata["body"].append(lf["text"])
            # pictures inside groups were missed by the top-level loop
            if lf["depth"] >= 1 and lf["shape_type"] == MSO_SHAPE_TYPE.PICTURE:
                sdata["images"].append({
                    "name": "group_pic",
                    "left_emu": lf["left"], "top_emu": lf["top"],
                    "width_emu": lf["w"], "height_emu": lf["h"],
                })
        sdata["group_nodes"] = group_nodes
        sdata["visual_kind"] = classify_visual_kind(sdata)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_walk_shapes.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run full unit suite to check no regressions**

Run: `pytest tests/unit/ -q`
Expected: PASS (existing tests green; `test_image_screenshot_frame`, `test_clean_slide_decor` unaffected)

- [ ] **Step 6: Commit**

```bash
git add skill_assets/scripts/parse_pptx.py tests/unit/test_walk_shapes.py
git commit -m "feat(parse): emit visual_kind + group_nodes per slide"
```

---

## Task 4: media_prep — produce image_path for raster/opaque slides

**Files:**
- Modify: `graph/nodes/pipeline.py`
- Test: `tests/unit/test_media_prep.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_media_prep.py
"""media_prep produces image_path for raster (extract) and opaque (render)."""
from __future__ import annotations

import os
from pathlib import Path

from graph.nodes.pipeline import _media_prep_for_slide


def test_raster_uses_extracted_image(tmp_path, monkeypatch):
    # Stub extractor: return a fake extracted file for slide 9.
    extracted = tmp_path / "slide9_img1.png"
    extracted.write_bytes(b"\x89PNG\r\n")

    def fake_extract(pptx, outdir, manifest=None):
        return {"images": [{"slide_num": 9, "file": extracted.name,
                            "width_px": 1149, "height_px": 535}]}

    monkeypatch.setattr("graph.nodes.pipeline.extract_images_extract", fake_extract)
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=9, visual_kind="raster",
        extract_dir=tmp_path, render_pngs={},
    )
    assert path is not None and path.endswith("slide9_img1.png")


def test_opaque_uses_rendered_png(tmp_path):
    rendered = tmp_path / "slide-08.png"
    rendered.write_bytes(b"\x89PNG\r\n")
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=8, visual_kind="opaque",
        extract_dir=tmp_path, render_pngs={8: str(rendered)},
    )
    assert path == str(rendered)


def test_opaque_without_render_returns_none(tmp_path):
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=8, visual_kind="opaque",
        extract_dir=tmp_path, render_pngs={},
    )
    assert path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_media_prep.py -v`
Expected: FAIL with `ImportError: cannot import name '_media_prep_for_slide'`

- [ ] **Step 3: Implement helpers in pipeline.py**

Add a module-level extractor indirection (so tests can monkeypatch it) near the other helpers:

```python
def extract_images_extract(pptx_path, out_dir, manifest=None):
    """Thin wrapper around the vendored extractor (monkeypatchable in tests)."""
    skill_bridge.install()
    import extract_images
    return extract_images.extract(str(pptx_path), str(out_dir), manifest)
```

Add the per-slide resolver:

```python
def _media_prep_for_slide(pptx_path, slide_num, visual_kind, extract_dir, render_pngs):
    """Return an image_path (str) for a raster/opaque slide, or None.

    raster → largest extracted picture on that slide.
    opaque → pre-rendered full-slide PNG from ``render_pngs`` (slide_num→path).
    Falls through to None when nothing is available (caller logs WARN).
    """
    if visual_kind == "raster":
        try:
            manifest = extract_images_extract(pptx_path, extract_dir)
        except Exception as e:
            logger.warning("media_prep.extract_failed", slide=slide_num, error=str(e))
            return None
        imgs = [im for im in manifest.get("images", []) if im.get("slide_num") == slide_num]
        if not imgs:
            return None
        best = max(imgs, key=lambda im: (im.get("width_px") or 0) * (im.get("height_px") or 0))
        return str(Path(extract_dir) / best["file"])
    if visual_kind == "opaque":
        return render_pngs.get(slide_num)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_media_prep.py -v`
Expected: PASS (all 3)

- [ ] **Step 5: Commit**

```bash
git add graph/nodes/pipeline.py tests/unit/test_media_prep.py
git commit -m "feat(pipeline): _media_prep_for_slide raster/opaque resolver"
```

---

## Task 5: Generalize slide rendering to all visual slides

**Files:**
- Modify: `graph/nodes/pipeline.py`
- Test: `tests/unit/test_media_prep.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
def test_render_all_slides_indexes_by_num(tmp_path, monkeypatch):
    from graph.nodes import pipeline

    # Simulate render output: directory with slide-01.png .. slide-03.png
    out = tmp_path / "render"
    out.mkdir()
    for i in (1, 2, 3):
        (out / f"slide-{i:02d}.png").write_bytes(b"\x89PNG\r\n")

    def fake_run(*a, **k):
        class R: returncode = 0; stderr = ""
        return R()

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline.tempfile, "mkdtemp", lambda prefix="": str(out))

    mapping = pipeline._render_all_slides_png(tmp_path / "dummy.pptx")
    assert set(mapping.keys()) == {1, 2, 3}
    assert mapping[2].endswith("slide-02.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_media_prep.py::test_render_all_slides_indexes_by_num -v`
Expected: FAIL with `AttributeError: ... has no attribute '_render_all_slides_png'`

- [ ] **Step 3: Implement `_render_all_slides_png` in pipeline.py**

```python
def _render_all_slides_png(pptx_path):
    """Render every slide to PNG via render_slides.py. Returns {slide_num: path}.

    Empty dict if soffice/pdftoppm unavailable (caller degrades). Output files
    are named slide-01.png, slide-02.png, … (1-based) by the vendored script.
    """
    script = Path(skill_bridge.SKILL_SCRIPTS) / "render_slides.py"
    if not script.is_file():
        return {}
    out_dir = Path(tempfile.mkdtemp(prefix="slidesbot_renderall_"))
    try:
        result = subprocess.run(
            [sys.executable, str(script), str(pptx_path), str(out_dir)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning("media_prep.render_all_failed",
                           stderr=result.stderr[-500:] if result.stderr else "")
            return {}
        mapping = {}
        for png in sorted(out_dir.glob("slide-*.png")):
            stem = png.stem.split("-")[-1]
            if stem.isdigit():
                mapping[int(stem)] = str(png)
        return mapping
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("media_prep.render_all_unavailable", error=str(e))
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_media_prep.py -v`
Expected: PASS (all 4)

- [ ] **Step 5: Commit**

```bash
git add graph/nodes/pipeline.py tests/unit/test_media_prep.py
git commit -m "feat(pipeline): _render_all_slides_png index by slide num"
```

---

## Task 6: Integrate media_prep into parse_node

**Files:**
- Modify: `graph/nodes/pipeline.py` (`parse_node`)

- [ ] **Step 1: Add media_prep block to parse_node**

In `parse_node`, replace the current grounding block:

```python
    png = _render_first_slide_png(path)
    if png is not None:
        arts["original_pngs"] = [png]
    else:
        arts.pop("original_pngs", None)
```

with the generalized version that handles all visual slides:

```python
    slides = deck.model_dump().get("slides", [])
    visual_nums = [s["num"] for s in slides
                   if s.get("visual_kind") in ("raster", "opaque")]

    render_pngs = {}
    if visual_nums:
        render_pngs = _render_all_slides_png(path)

    # Grounding: slide 1 always; plus every visual slide we rendered.
    grounding = []
    first = _render_first_slide_png(path)
    if first is not None:
        grounding.append(first)
    for n in visual_nums:
        p = render_pngs.get(n)
        if p and p not in grounding:
            grounding.append(p)
    if grounding:
        arts["original_pngs"] = grounding
    else:
        arts.pop("original_pngs", None)

    # Resolve image_path per visual slide and stitch it back into parsed_deck.
    extract_dir = Path(tempfile.mkdtemp(prefix="slidesbot_extract_"))
    pd = arts["parsed_deck"]
    for s in pd.get("slides", []):
        vk = s.get("visual_kind")
        if vk not in ("raster", "opaque"):
            continue
        img_path = _media_prep_for_slide(
            pptx_path=path, slide_num=s["num"], visual_kind=vk,
            extract_dir=extract_dir, render_pngs=render_pngs,
        )
        if img_path:
            s["image_path"] = img_path
            logger.info("media_prep.visual_route", slide=s["num"],
                        kind=vk, route=("image_a" if vk == "raster" else "image_b"),
                        image_path=img_path)
        else:
            logger.warning("media_prep.no_image", slide=s["num"], kind=vk)
    arts["parsed_deck"] = pd
```

- [ ] **Step 2: Smoke-run the integration test**

Run: `pytest tests/integration/test_pipeline_smoke.py -q`
Expected: PASS (no crash; smoke deck has no visual slides so media_prep is inert)

- [ ] **Step 3: Commit**

```bash
git add graph/nodes/pipeline.py
git commit -m "feat(pipeline): wire media_prep + multi-slide grounding into parse_node"
```

---

## Task 7: Classifier prompt — route visual_kind

**Files:**
- Modify: `llm/prompts/agent_02_slide_classifier.py`

- [ ] **Step 1: Add a visual_kind routing rule to the prompt**

Locate the `ПРАВИЛО МАППИНГА intent → category` section. Add a block ahead of the existing intent rules (the model receives `visual_kind` and `group_nodes` per slide from parsed_deck via the brief):

```python
# (inside the prompt string, in the mapping-rules section)
"""
ПРАВИЛО ДЛЯ ВИЗУАЛЬНЫХ СЛАЙДОВ (visual_kind — приоритет над intent):
- visual_kind="structured": слайд содержит group_nodes (текстовые узлы из
  сгруппированной диаграммы). Собери flow_diagram_native:
    • узлы с числовой нумерацией ("1","2",… + подпись) → flow.preset="numbered_rows",
      flow.rows=[{{num, title|text}}] в порядке order.
    • параллельные узлы "заголовок + фраза" без нумерации → flow.preset="card_grid",
      flow.cards=[{{title, text}}]. cols: 2 (≤4) / 3 (5-6) / 4 (7-8).
    category=other. НЕ выбирай image_native для structured.
- visual_kind="raster" ИЛИ "opaque": слайд несёт готовый image_path (он уже
  проставлен в данных). Выбери slide_type="image_native",
  image={{title: <краткий заголовок>, image_path: <как в данных>,
  caption: "", subcategory: "diagram"}}.
"""
```

- [ ] **Step 2: Verify the prompt string still imports cleanly**

Run: `python -c "import llm.prompts.agent_02_slide_classifier as m; print(bool(m))"`
Expected: prints `True` (no syntax error)

- [ ] **Step 3: Commit**

```bash
git add llm/prompts/agent_02_slide_classifier.py
git commit -m "feat(agent02): route visual_kind structured→flow, raster/opaque→image"
```

---

## Task 8: Integration verification on dl2 (worker)

**Files:** none (verification only). Run in the worker container.

- [ ] **Step 1: Sync changed files into the worker**

```bash
for f in skill_assets/scripts/parse_pptx.py skill_assets/scripts/visual_kind.py \
         graph/nodes/pipeline.py llm/prompts/agent_02_slide_classifier.py; do
  MSYS_NO_PATHCONV=1 docker exec -i slides-bot-worker sh -c "cat > /app/$f" < "$f"
done
echo synced
```

- [ ] **Step 2: Launch a grounded dl2 live run**

```bash
MSYS_NO_PATHCONV=1 docker exec -d -w /app -e LIVE_RUN_INPUT=/tmp/dl/dl2.pptx \
  slides-bot-worker sh -c "python -m scripts.live_run > /tmp/dl/wlive_dl2_recon.log 2>&1"
```

- [ ] **Step 3: After completion, check drop count + routing**

```bash
MSYS_NO_PATHCONV=1 docker exec slides-bot-worker sh -c \
  "grep -E 'node.assemble.done|media_prep.visual_route|media_prep.no_image' /tmp/dl/wlive_dl2_recon.log"
```
Expected: `skipped=[]` (0 drops) and `visual_route` lines for slides 8/9/11/31 etc.

- [ ] **Step 4: Render output deck + visually inspect key slides**

```bash
MSYS_NO_PATHCONV=1 docker exec slides-bot-worker sh -c "
  S=\$(ls -t /var/lib/slidesbot/sessions | head -1)
  soffice --headless --convert-to pdf --outdir /tmp/dl /var/lib/slidesbot/sessions/\$S/result.pptx >/dev/null 2>&1
  pdftoppm -png -r 90 /tmp/dl/result.pdf /tmp/dl/dl2recon"
```
Copy slides 8, 9, 11, 31 to host and Read them. Verify:
- slide 8 → native numbered/card diagram (NOT an image)
- slide 9 → clean extracted-raster insert
- slides 11, 31 → full-bleed rendered image on branded layout

- [ ] **Step 5: Regression — re-run dl1 and dl3, confirm no new drops/defects**

```bash
for d in dl1 dl3; do
  MSYS_NO_PATHCONV=1 docker exec -d -w /app -e LIVE_RUN_INPUT=/tmp/dl/$d.pptx \
    slides-bot-worker sh -c "python -m scripts.live_run > /tmp/dl/wlive_${d}_recon.log 2>&1"
done
```
After completion: confirm dl1 still 9 built, dl3 still 5 built, no new skipped slides.

- [ ] **Step 6: Definition of Done check**

- dl2: 36/36 in output (0 drops); slide 8 rebuilt as native layout (not image).
- dl1/dl3: no regression.
- `pytest tests/unit/ -q` green.

Do NOT commit code in this task (verification only). Report results to the user.

---

## Self-Review Notes

- **Spec coverage:** §3 flow → Tasks 1,3,6; §4.1 `_walk_shapes` → Task 1; §4.2 parse fields → Task 3; §4.3 `classify_visual_kind` → Task 2; §4.4 media_prep → Tasks 4,5,6; §4.5 prompts → Task 7; §5 thresholds → Task 2 constants; §6 unit tests → Tasks 1-5, integration → Task 8.
- **Fallback chain (§5):** raster/opaque resolver returns None when no image available; parse_node logs `media_prep.no_image` WARN. The C→B reconstruction-failure path is handled by the classifier prompt (Task 7) choosing image_native when it cannot map nodes; build_v9 already drops only if image_path absent.
- **Type consistency:** `_media_prep_for_slide(pptx_path, slide_num, visual_kind, extract_dir, render_pngs)` signature identical across Task 4 def and Task 6 call. `_render_all_slides_png` returns `{int: str}` used as `render_pngs` in both. `visual_kind` values `none|structured|raster|opaque` consistent across visual_kind.py, parse_pptx, prompt.
