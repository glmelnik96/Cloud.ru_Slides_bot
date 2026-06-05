# Visual Quality Phase D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap to the Cloud.ru template's full design vocabulary by adopting 5 reference patterns (editorial chart, inline phrase emphasis, inline KPI layout, reclaimed decor + centering, screenshot frame).

**Architecture:** Five mostly-independent renderer changes (D1–D5) in `skill_assets/scripts/`, each guarded so the default path is unchanged. Triggers are threaded from Agent 02/03/04 prompts. All renderers run on the host during `build_v9`; PNGs render in the `slides-bot-worker` container. TDD with unit tests under `tests/unit/`.

**Tech Stack:** python-pptx (CategoryChartData native charts, lxml XML run-mutation), PIL (image sizing), pytest. Tests import skill scripts via `from worker import skill_bridge; skill_bridge.install()`.

**Spec:** `docs/superpowers/specs/2026-06-06-visual-quality-phase-d-design.md`

---

## File Structure

- `skill_assets/scripts/kpi_emphasis.py` — **D2**: add `**phrase**` markup emphasis + a markup-strip pass; thread `emphasize_phrases`/`dark` through `emphasize_kpi_in_slide` and `apply_kpi_emphasis`.
- `skill_assets/scripts/kpi_renderer.py` — **D3** (`render_kpi` geometry → number-left/desc-right inline, larger `%`); **D4 part 1** (`clean_slide_to_blank` gains `keep_decor` + content-zone overlap guard).
- `skill_assets/scripts/chart_native_pptx.py` — **D1**: `style="editorial"` single-series path (per-bar green ramp via N single-value series + white выноска overlay on dark slide).
- `skill_assets/scripts/flow_renderer.py` — **D4 part 2**: vertical-center short content in `render_card_grid`.
- `skill_assets/scripts/image_renderer.py` — **D5**: browser-chrome frame when screenshot.
- `llm/prompts/agent_02_slide_classifier.py` — emit `chart.style="editorial"` + `image` screenshot frame hint.
- `llm/prompts/agent_03_content_distributor.py` — mark one key phrase per body paragraph with `**…**`.
- `tests/unit/test_kpi_emphasis.py` — extend (D2).
- `tests/unit/test_kpi_inline_layout.py` — new (D3).
- `tests/unit/test_chart_editorial.py` — new (D1).
- `tests/unit/test_clean_slide_decor.py` — new (D4 part 1).
- `tests/unit/test_card_grid_centering.py` — new (D4 part 2).
- `tests/unit/test_image_screenshot_frame.py` — new (D5).
- `tmp/p11/make_deck_d.py`, `tmp/p11/make_deck_e.py` — new test decks (D5 screenshots; D1+D2 editorial chart + inline phrase).

---

## Task 1: D2 — Inline green phrase emphasis

**Files:**
- Modify: `skill_assets/scripts/kpi_emphasis.py`
- Test: `tests/unit/test_kpi_emphasis.py`

**Design:** Agent 03 marks one key phrase per body paragraph with `**…**`. A new pass strips the markup and applies the existing run-split styling (bold + `#26D07C`) to the marked span. Guardrails: at most ONE phrase per paragraph; ≤6 words; skip emphasis (but still strip markup) on dark slides; skip `kpi_native` slides (already skipped).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_kpi_emphasis.py`:

```python
# ─── D2: inline phrase emphasis (**markup**) ──────────────────────────────────

from kpi_emphasis import emphasize_phrases_in_slide  # noqa: E402


def test_phrase_emphasis_marks_one_phrase(blank_slide) -> None:
    prs, slide = blank_slide
    _add_textbox(slide, "Платформа даёт **полную изоляцию данных** для клиентов",
                 size_pt=14)
    n = emphasize_phrases_in_slide(slide, emphasis_hex="26D07C")
    assert n == 1
    assert _count_emphasized_runs_with_color(slide, "26D07C") == 1
    # markup stripped — no literal asterisks remain.
    assert "**" not in slide.shapes[-1].text_frame.text
    assert "полную изоляцию данных" in slide.shapes[-1].text_frame.text


def test_phrase_emphasis_at_most_one_per_paragraph(blank_slide) -> None:
    prs, slide = blank_slide
    _add_textbox(slide, "**первая** и потом **вторая** фраза", size_pt=14)
    n = emphasize_phrases_in_slide(slide, emphasis_hex="26D07C")
    # Only the first marked phrase is emphasized; the rest is de-marked plain.
    assert n == 1
    assert _count_emphasized_runs_with_color(slide, "26D07C") == 1
    assert "**" not in slide.shapes[-1].text_frame.text


def test_phrase_emphasis_skips_long_phrase(blank_slide) -> None:
    prs, slide = blank_slide
    _add_textbox(slide, "итог **одно два три четыре пять шесть семь слов тут**",
                 size_pt=14)
    n = emphasize_phrases_in_slide(slide, emphasis_hex="26D07C")
    assert n == 0
    # markup is still stripped even when not emphasized.
    assert "**" not in slide.shapes[-1].text_frame.text


def test_phrase_emphasis_strips_markup_without_color_on_dark(blank_slide) -> None:
    """On dark slides we strip markup but do NOT emphasize (canon: no green
    text where it would clash). emphasis_hex=None means strip-only."""
    prs, slide = blank_slide
    _add_textbox(slide, "тёмный слайд с **важной фразой** внутри", size_pt=14)
    n = emphasize_phrases_in_slide(slide, emphasis_hex=None)
    assert n == 0
    assert "**" not in slide.shapes[-1].text_frame.text
    assert "важной фразой" in slide.shapes[-1].text_frame.text


def test_phrase_emphasis_noop_without_markup(blank_slide) -> None:
    prs, slide = blank_slide
    before = "обычный текст без разметки совсем"
    _add_textbox(slide, before, size_pt=14)
    n = emphasize_phrases_in_slide(slide, emphasis_hex="26D07C")
    assert n == 0
    assert slide.shapes[-1].text_frame.text.strip() == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_kpi_emphasis.py -k phrase -v`
Expected: FAIL with `ImportError: cannot import name 'emphasize_phrases_in_slide'`

- [ ] **Step 3: Implement the phrase-emphasis pass**

In `skill_assets/scripts/kpi_emphasis.py`, after `_emphasize_paragraph` (ends line 242), add:

```python
# D2 (2026-06-06): inline key-phrase emphasis. Agent 03 marks ONE key phrase
# per body paragraph with **…**. We strip the markup and (on light slides)
# bold+green the span — matching template slide 28. Guardrails: ≤1 phrase per
# paragraph, ≤6 words; on dark slides emphasis_hex=None → strip-only.
_PHRASE_RE = re.compile(r"\*\*(?P<phrase>[^*]+?)\*\*")
_PHRASE_MAX_WORDS = 6


def _emphasize_phrase_paragraph(p_el: etree._Element, *,
                                emphasis_hex: str | None) -> int:
    """Strip the first **…** span in the paragraph; if ``emphasis_hex`` is set
    and the phrase is ≤_PHRASE_MAX_WORDS words, bold+colour it. All remaining
    **…** markers in the paragraph are stripped to plain text. Returns 1 if a
    phrase was emphasized, else 0."""
    runs = p_el.findall(qn("a:r"))
    if not runs:
        return 0
    emphasized = 0
    for r in list(runs):
        if emphasized:  # already used our one-per-paragraph budget
            _strip_markers_in_run(r)
            continue
        t_el = r.find(qn("a:t"))
        if t_el is None or not t_el.text or "**" not in t_el.text:
            continue
        text = t_el.text
        m = _PHRASE_RE.search(text)
        if m is None:
            _strip_markers_in_run(r)
            continue
        phrase = m.group("phrase")
        n_words = len([w for w in phrase.split() if w])
        do_color = emphasis_hex is not None and 1 <= n_words <= _PHRASE_MAX_WORDS
        parent = r.getparent()
        insert_idx = list(parent).index(r)
        new_runs: list[etree._Element] = []
        # pre
        if m.start() > 0:
            pre = deepcopy(r)
            pre.find(qn("a:t")).text = text[:m.start()]
            new_runs.append(pre)
        # phrase
        ph = deepcopy(r)
        ph.find(qn("a:t")).text = phrase
        if do_color:
            ph_rPr = ph.find(qn("a:rPr"))
            if ph_rPr is None:
                ph_rPr = etree.SubElement(ph, qn("a:rPr"))
                ph.insert(0, ph_rPr)
            _set_run_emphasis(ph_rPr, color_hex=emphasis_hex)
            emphasized = 1
        new_runs.append(ph)
        # tail (markers in the tail are stripped on subsequent iterations)
        if m.end() < len(text):
            tail = deepcopy(r)
            tail.find(qn("a:t")).text = text[m.end():]
            new_runs.append(tail)
        parent.remove(r)
        for i, nr in enumerate(new_runs):
            parent.insert(insert_idx + i, nr)
    return emphasized


def _strip_markers_in_run(r: etree._Element) -> None:
    """Remove any literal ** markers from a run's text in place."""
    t_el = r.find(qn("a:t"))
    if t_el is not None and t_el.text and "**" in t_el.text:
        t_el.text = t_el.text.replace("**", "")


def emphasize_phrases_in_slide(slide, *, emphasis_hex: str | None) -> int:
    """Apply D2 phrase emphasis to every non-title body shape. Returns the
    number of phrases emphasized on the slide."""
    total = 0
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        if _shape_is_title_like(shape):
            continue
        txBody = shape.text_frame._txBody
        for p_el in txBody.findall(qn("a:p")):
            try:
                total += _emphasize_phrase_paragraph(p_el, emphasis_hex=emphasis_hex)
            except Exception as e:  # noqa: BLE001 — never fail the build
                print(f"WARN: phrase emphasis paragraph failed: {e}",
                      file=sys.stderr)
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_kpi_emphasis.py -k phrase -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire into `apply_kpi_emphasis`**

In `skill_assets/scripts/kpi_emphasis.py`, replace the body loop of `apply_kpi_emphasis` (lines 325–335, from `slides = list(prs.slides)` through `return {...}`) with:

```python
    slides = list(prs.slides)
    phrases = 0
    for idx, slide in enumerate(slides):
        plan = (plan_slides[idx] or {}) if plan_slides and idx < len(plan_slides) else {}
        st = plan.get("slide_type")
        if st in skip_types:
            continue
        # D2: phrase emphasis — green on light, strip-only on dark.
        dark = bool(plan.get("dark", False))
        phrases += emphasize_phrases_in_slide(
            slide, emphasis_hex=(None if dark else _GREEN_HEX))
        # Numeric auto-green pass (unchanged).
        n = emphasize_kpi_in_slide(slide)
        if n:
            total += n
            touched += 1
    return {"total": total, "slides_touched": touched, "phrases": phrases}
```

- [ ] **Step 6: Run the full emphasis suite (regression)**

Run: `python -m pytest tests/unit/test_kpi_emphasis.py -v`
Expected: PASS (all pre-existing + 5 new). The `phrases` key is additive; existing assertions on `total`/`slides_touched` still hold.

- [ ] **Step 7: Commit**

```bash
git add skill_assets/scripts/kpi_emphasis.py tests/unit/test_kpi_emphasis.py
git commit -m "$(cat <<'EOF'
D2: inline key-phrase emphasis (**markup**) in kpi_emphasis

Strip Agent-03 **…** markup and bold+green one key phrase per body
paragraph (template slide 28). Strip-only on dark slides; ≤6 words.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: D3 — KPI inline layout (number-left / desc-right)

**Files:**
- Modify: `skill_assets/scripts/kpi_renderer.py:217-322` (`render_kpi`)
- Test: `tests/unit/test_kpi_inline_layout.py`

**Design:** Restructure each KPI cell from centered-number-with-desc-below to **number left-aligned / description to its right, vertically centered** (template slide 43). Enlarge the attached `%` to ≈0.5× number height, kerned to the number's top-right. Color stays graphite (canon). Recompute column x/width for n=1/2/3 so the number+desc pair fits.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_kpi_inline_layout.py`:

```python
"""D3: KPI inline layout — number left / description right, vertically centered."""
from __future__ import annotations

import pytest

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402

from kpi_renderer import render_kpi, clean_slide_to_blank, BLANK_DONOR_WHITE  # noqa: E402


def _blank():
    prs = Presentation(str(skill_bridge.TEMPLATE_PATH))
    slide = list(prs.slides)[BLANK_DONOR_WHITE - 1]
    clean_slide_to_blank(slide)
    return prs, slide


def _textboxes(slide):
    return [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip()]


def test_desc_sits_right_of_number(_blank=_blank):
    prs, slide = _blank()
    render_kpi(slide, {"title": "ИТОГ", "numbers": [
        {"value": "84", "desc": "вовлечённость команды"}]})
    boxes = _textboxes(slide)
    num = next(b for b in boxes if b.text_frame.text == "84")
    desc = next(b for b in boxes if "вовлечённость" in b.text_frame.text)
    # Description box must start to the right of the number box.
    assert desc.left > num.left
    # And overlap the number vertically (inline, not stacked below).
    n_top, n_bot = num.top, num.top + num.height
    d_mid = desc.top + desc.height // 2
    assert n_top <= d_mid <= n_bot


def test_pct_is_enlarged(_blank=_blank):
    prs, slide = _blank()
    render_kpi(slide, {"title": "ИТОГ", "numbers": [
        {"value": "99", "desc": "аптайм", "pct": True}]})
    boxes = [s for s in slide.shapes if s.has_text_frame
             and s.text_frame.text.strip() == "%"]
    assert len(boxes) == 1
    pct = boxes[0]
    # Enlarged %: font ≈ 0.5× number height. For the single hero (199pt)
    # the % must be ≥ 80pt (was max(40, 199//3)=66).
    sz = pct.text_frame.paragraphs[0].runs[0].font.size.pt
    assert sz >= 80


@pytest.mark.parametrize("n", [1, 2, 3])
def test_columns_do_not_overlap(n):
    prs, slide = _blank()
    nums = [{"value": str(10 + i), "desc": f"метрика {i}"} for i in range(n)]
    render_kpi(slide, {"title": "T", "numbers": nums})
    # Number boxes, left-to-right, must not overlap horizontally.
    num_boxes = sorted(
        [s for s in slide.shapes if s.has_text_frame
         and s.text_frame.text.strip().isdigit()],
        key=lambda b: b.left)
    for a, b in zip(num_boxes, num_boxes[1:]):
        assert a.left + a.width <= b.left + 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_kpi_inline_layout.py -v`
Expected: FAIL — `test_desc_sits_right_of_number` fails (current desc is below, centered), `test_pct_is_enlarged` fails (current % is 66pt).

- [ ] **Step 3: Rewrite `render_kpi` geometry**

In `skill_assets/scripts/kpi_renderer.py`, replace the block from `# Number boxes layout` (line 243) through the end of the `for` loop (line 322) with:

```python
    # D3 (2026-06-06): inline layout — number LEFT, description RIGHT, vertically
    # centered (template slide 43). Color stays graphite (canon 2026-05-29).
    if n == 1:
        col_x = [60]
        col_w = [1160]
    elif n == 2:
        col_x = [60, 660]
        col_w = [560, 560]
    else:  # n == 3
        col_x = [40, 440, 840]
        col_w = [380, 380, 380]

    ROW_TOP = 240
    ROW_HEIGHT = 240
    NUMBER_FONT = 150 if n == 1 else (110 if n == 2 else 90)
    if n == 3:
        max_chars = max(len(str(x["value"])) for x in kpi_config["numbers"])
        if max_chars > 3:
            NUMBER_FONT = 76
    # Number box width ≈ digits-driven; description fills the rest of the column.
    DESC_FONT = 16 if n == 1 else (14 if n == 2 else 12)

    for i, num in enumerate(kpi_config["numbers"]):
        x = col_x[i]
        w = col_w[i]
        color = text_color  # graphite/white — never the accent itself
        value = num["value"]
        has_pct = num.get("pct", False)

        # Defensive normalize (live run 2026-06-05): value may carry a trailing
        # '%'; strip it and route through pct so '%' isn't doubled.
        if isinstance(value, str) and value.rstrip().endswith("%"):
            value = value.rstrip()[:-1].rstrip()
            has_pct = True

        if NUMBER_FONT >= 150:
            digits = _count_significant_digits(value)
            if digits > KPI_HERO_DIGIT_LIMIT:
                print(
                    f"WARN: KPI value '{value}' содержит {digits} значащих цифр "
                    f"при {NUMBER_FONT}pt frame (canonical max {KPI_HERO_DIGIT_LIMIT}).",
                    file=sys.stderr,
                )

        # Number box: left-aligned, width sized to the value (~0.62×font per digit).
        num_w = max(120, int(len(str(value)) * NUMBER_FONT * 0.62) + 40)
        num_w = min(num_w, w - 120)  # always leave ≥120px for the description
        _add_text_box(slide, x, ROW_TOP, num_w, ROW_HEIGHT,
                      value, font_size_pt=NUMBER_FONT, bold=False, color=color,
                      align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)

        # Enlarged %: ≈0.5× number height, kerned to the number's top-right.
        if has_pct:
            pct_size = max(80, NUMBER_FONT // 2)
            pct_x = x + num_w - 24
            pct_y = ROW_TOP + 10
            _add_text_box(slide, pct_x, pct_y, 90, 120, "%",
                          font_size_pt=pct_size, bold=True, color=color,
                          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP)

        # Green underline-plate accent under the number (canon: accent is the
        # plate, not a green number).
        if num.get("accent", False):
            _add_accent_bar(slide, x, ROW_TOP + ROW_HEIGHT - 8,
                            num_w, 8, color=GREEN)

        # Description: to the RIGHT of the number, vertically centered to it.
        desc = num.get("desc", "")
        if desc:
            desc_x = x + num_w + 16
            desc_w = x + w - desc_x
            _add_text_box(slide, desc_x, ROW_TOP, max(80, desc_w), ROW_HEIGHT,
                          desc, font_size_pt=DESC_FONT, bold=False,
                          color=text_color,
                          align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_kpi_inline_layout.py -v`
Expected: PASS (5 tests: desc-right, pct-enlarged, 3× no-overlap)

- [ ] **Step 5: Commit**

```bash
git add skill_assets/scripts/kpi_renderer.py tests/unit/test_kpi_inline_layout.py
git commit -m "$(cat <<'EOF'
D3: KPI inline layout — number-left / desc-right, larger %

Restructure render_kpi to template slide 43's inline geometry; enlarge
the attached % to ~0.5x number height. Color stays graphite (canon).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: D1 — Editorial chart (per-bar green ramp on dark + выноска)

**Files:**
- Modify: `skill_assets/scripts/chart_native_pptx.py`
- Test: `tests/unit/test_chart_editorial.py`

**Design:** Add an `style="editorial"` path for **single-series bar** charts. Restructure the one series into N single-value series so each bar carries its own color → graduated green ramp (dark→bright), `accent_idx` bar brightest (`#26D07C`). Render on a dark slide; overlay a large white "выноска" number (peak or total) to the right of the plot ~150pt. Stays a real native chart (editable). Multi-series / non-bar charts keep the current uniform path.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_chart_editorial.py`:

```python
"""D1: editorial single-series bar chart — per-bar green ramp + выноска overlay."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE_TYPE  # noqa: E402

from chart_native_pptx import (  # noqa: E402
    _green_ramp, is_editorial_eligible, render_chart_pptx_slide,
)


def test_green_ramp_dark_to_bright_with_accent():
    ramp = _green_ramp(4, accent_idx=3)
    assert len(ramp) == 4
    # Accent bar is the brightest brand green (#26D07C).
    assert str(ramp[3]).upper() == "26D07C"
    # Earlier bars are darker (lower luminance) than the accent.
    def lum(c):
        h = str(c)
        return int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)
    assert lum(ramp[0]) < lum(ramp[3])


def test_editorial_eligible_only_single_series_bar():
    assert is_editorial_eligible(
        {"type": "bar", "style": "editorial",
         "series": [{"name": "a", "data": [1, 2, 3]}]}) is True
    # Multi-series → not eligible.
    assert is_editorial_eligible(
        {"type": "bar", "style": "editorial",
         "series": [{"name": "a", "data": [1]}, {"name": "b", "data": [2]}]}) is False
    # Non-bar → not eligible.
    assert is_editorial_eligible(
        {"type": "line", "style": "editorial",
         "series": [{"name": "a", "data": [1, 2]}]}) is False
    # No editorial style → not eligible.
    assert is_editorial_eligible(
        {"type": "bar", "series": [{"name": "a", "data": [1, 2]}]}) is False


def test_editorial_render_splits_bars_and_overlays_number():
    prs = Presentation(str(skill_bridge.TEMPLATE_PATH))
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(layout)
    render_chart_pptx_slide(slide, {
        "title": "Динамика числа клиентов",
        "type": "bar", "style": "editorial",
        "x": [2023, 2024, 2025, 2026],
        "series": [{"name": "Клиенты", "data": [120, 340, 720, 1280]}],
        "accent_idx": 3,
    }, dark=True)
    # One native chart object with N single-value series (one per bar).
    charts = [s for s in slide.shapes if s.has_chart]
    assert len(charts) == 1
    assert len(list(charts[0].chart.series)) == 4
    # A large выноска number textbox carrying the peak value.
    texts = [s.text_frame.text for s in slide.shapes
             if s.has_text_frame]
    assert any("1280" in t for t in texts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_chart_editorial.py -v`
Expected: FAIL with `ImportError: cannot import name '_green_ramp'`

- [ ] **Step 3: Implement the editorial path**

In `skill_assets/scripts/chart_native_pptx.py`, after `NON_ACCENT_COLORS = _build_non_accent_colors()` (line 91), add:

```python
def _green_ramp(n: int, accent_idx: int = -1) -> list:
    """Return n RGBColors ramping dark→bright green; the accent bar gets the
    brand green (#26D07C, brightest). Used by the editorial single-series path
    where each bar is its own single-value series."""
    if n <= 0:
        return []
    # Dark→bright endpoints (graphite-green → brand green).
    lo = (0x0E, 0x5A, 0x38)
    hi = (0x26, 0xD0, 0x7C)
    out = []
    for i in range(n):
        t = i / max(n - 1, 1)
        rgb = tuple(int(lo[c] + (hi[c] - lo[c]) * t) for c in range(3))
        out.append(RGBColor(*rgb))
    if 0 <= accent_idx < n:
        out[accent_idx] = RGBColor(0x26, 0xD0, 0x7C)
    return out


def is_editorial_eligible(chart_config: dict) -> bool:
    """Editorial path applies only to single-series bar charts marked
    style='editorial'. Everything else keeps the clean uniform chart."""
    if chart_config.get("style") != "editorial":
        return False
    if chart_config.get("type") != "bar":
        return False
    series = chart_config.get("series") or []
    return len(series) == 1
```

- [ ] **Step 4: Branch `add_chart_to_slide` to split bars**

In `skill_assets/scripts/chart_native_pptx.py`, inside `add_chart_to_slide`, replace the category/series build block (lines 159–172, from `if ctype == XL_CHART_TYPE.PIE:` through the `_apply_series_colors(chart, accent_idx)` call) with:

```python
    editorial = is_editorial_eligible(chart_config)
    accent_idx = chart_config.get("accent_idx", -1)

    cd = CategoryChartData()
    if ctype == XL_CHART_TYPE.PIE:
        cd.categories = [str(x) for x in chart_config["labels"]]
        cd.add_series("", chart_config["values"])
    elif editorial:
        # Split the single series into N single-value series so each bar
        # carries its own colour (native charts have no per-point bar fill).
        data = chart_config["series"][0]["data"]
        cats = [str(x) for x in chart_config["x"]]
        cd.categories = cats
        for i, v in enumerate(data):
            row = [None] * len(data)
            row[i] = v
            cd.add_series(cats[i], row)
    else:
        cd.categories = [str(x) for x in chart_config["x"]]
        for s in chart_config["series"]:
            cd.add_series(s["name"], s["data"])

    chart_shape = slide.shapes.add_chart(ctype, left, top, width, height, cd)
    chart = chart_shape.chart

    if ctype == XL_CHART_TYPE.PIE:
        plot = chart.plots[0]
        for i, point in enumerate(plot.series[0].points):
            color = GREEN if i == accent_idx else NON_ACCENT_COLORS[
                min(i, len(NON_ACCENT_COLORS) - 1)
            ]
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = color
    elif editorial:
        ramp = _green_ramp(len(list(chart.series)), accent_idx)
        chart.has_legend = False
        for i, s in enumerate(chart.series):
            fill = s.format.fill
            fill.solid()
            fill.fore_color.rgb = ramp[i]
            s.format.line.fill.background()
        try:
            chart.plots[0].gap_width = 60
            chart.plots[0].overlap = 100  # bars share the category slot
        except Exception:
            pass
    else:
        _apply_series_colors(chart, accent_idx)
```

Then DELETE the now-duplicated pie-point colouring block (old lines 173–180, the `else:` branch beginning `plot = chart.plots[0]`) and the standalone `accent_idx = chart_config.get("accent_idx", -1)` line (old line 170) — both are folded into the block above. Keep everything from `text_color = ...` (old line 182) onward unchanged, except the legend: editorial sets `has_legend=False` above, so the unconditional `chart.has_legend = True` block (old lines 191–200) must be guarded:

```python
    if ctype != XL_CHART_TYPE.PIE and not editorial:
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        try:
            chart.legend.font.size = Pt(10)
            chart.legend.font.color.rgb = text_color
            chart.legend.font.name = "SB Sans Display"
        except Exception:
            pass
```

- [ ] **Step 5: Add the выноска overlay + dark default in `render_chart_pptx_slide`**

In `skill_assets/scripts/chart_native_pptx.py`, modify `render_chart_pptx_slide`. At the top of the function (after `text_color = ...`, line 230), force dark for editorial and shrink the plot zone so the выноска fits:

```python
    editorial = is_editorial_eligible(chart_config)
    if editorial:
        dark = True
        text_color = WHITE
```

Then replace the `ZONE_X, ZONE_Y, ZONE_W, ZONE_H = 60, 120, 1160, 480` line (line 237) and the `add_chart_to_slide(...)` call with:

```python
    if editorial:
        ZONE_X, ZONE_Y, ZONE_W, ZONE_H = 60, 150, 760, 450  # leave right gutter
    else:
        ZONE_X, ZONE_Y, ZONE_W, ZONE_H = 60, 120, 1160, 480
    chart_inner_cfg = {k: v for k, v in chart_config.items()
                       if k not in ("title", "slide_title", "caption")}

    add_chart_to_slide(
        slide, chart_inner_cfg,
        Emu(ZONE_X * 9525), Emu(ZONE_Y * 9525),
        Emu(ZONE_W * 9525), Emu(ZONE_H * 9525),
        dark=dark,
    )

    if editorial:
        # Large white выноска (peak value) to the right of the plot.
        data = chart_config["series"][0]["data"]
        acc = chart_config.get("accent_idx", -1)
        peak = data[acc] if 0 <= acc < len(data) else max(data)
        _add_text_box(slide, ZONE_X + ZONE_W + 20, 180, 380, 360,
                      str(peak), font_size_pt=150, bold=True, color=WHITE,
                      align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE)
```

(`_add_text_box`, `PP_ALIGN`, `MSO_ANCHOR` are already imported inside the function at lines 226–227.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_chart_editorial.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Verify the standard chart path still works (regression)**

Run: `cd skill_assets/scripts && python chart_native_pptx.py /tmp/chart_smoke.pptx && python -c "from pptx import Presentation; p=Presentation('/tmp/chart_smoke.pptx'); s=list(p.slides)[0]; assert any(sh.has_chart for sh in s.shapes); print('OK')"`
Expected: `Saved /tmp/chart_smoke.pptx` then `OK`

- [ ] **Step 8: Commit**

```bash
git add skill_assets/scripts/chart_native_pptx.py tests/unit/test_chart_editorial.py
git commit -m "$(cat <<'EOF'
D1: editorial single-series bar chart (green ramp on dark + выноска)

Add style="editorial" path: split one series into N single-value series
for a per-bar dark->bright green ramp on a dark slide, with a large white
peak-number overlay. Chart stays a native editable object.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: D4 part 1 — preserve template decor pics + content-zone overlap guard

**Files:**
- Modify: `skill_assets/scripts/kpi_renderer.py:164-185` (`clean_slide_to_blank`)
- Test: `tests/unit/test_clean_slide_decor.py`

**Design:** Make `clean_slide_to_blank` strip mock *text* shapes and content placeholders but, when `keep_decor=True`, **preserve `pic` shapes** that are template decoration — unless a pic intersects the active content zone (then still remove it). Default `keep_decor=False` keeps every existing caller's behavior identical.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_clean_slide_decor.py`:

```python
"""D4 part 1: clean_slide_to_blank can preserve decorative pics outside the
content zone, while still removing pics that overlap content."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402
from pptx.util import Emu  # noqa: E402

from kpi_renderer import clean_slide_to_blank, CONTENT_ZONE_EMU  # noqa: E402

_PX = 9525
_IMG = str(skill_bridge.TEMPLATE_PATH)  # any file path is fine for add_picture? no — use png


def _png(tmp_path):
    from PIL import Image
    p = tmp_path / "dot.png"
    Image.new("RGB", (10, 10), (0, 200, 120)).save(p)
    return str(p)


def _slide_with_pic(prs, left_px, top_px, w_px, h_px, png):
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.add_picture(png, Emu(left_px * _PX), Emu(top_px * _PX),
                             Emu(w_px * _PX), Emu(h_px * _PX))
    return slide


def _count_pics(slide):
    return sum(1 for s in slide.shapes if s.shape_type == 13)  # PICTURE


def test_default_strips_all_pics(tmp_path):
    png = _png(tmp_path)
    prs = Presentation()
    slide = _slide_with_pic(prs, 1100, 20, 150, 150, png)  # corner decor
    clean_slide_to_blank(slide)  # keep_decor defaults False
    assert _count_pics(slide) == 0


def test_keep_decor_preserves_corner_pic(tmp_path):
    png = _png(tmp_path)
    prs = Presentation()
    slide = _slide_with_pic(prs, 1100, 20, 150, 150, png)  # top-right corner
    clean_slide_to_blank(slide, keep_decor=True)
    assert _count_pics(slide) == 1


def test_keep_decor_removes_content_zone_pic(tmp_path):
    png = _png(tmp_path)
    prs = Presentation()
    # Pic squarely inside the content zone — must be removed even with keep_decor.
    slide = _slide_with_pic(prs, 300, 300, 600, 300, png)
    clean_slide_to_blank(slide, keep_decor=True)
    assert _count_pics(slide) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_clean_slide_decor.py -v`
Expected: FAIL with `ImportError: cannot import name 'CONTENT_ZONE_EMU'`

- [ ] **Step 3: Implement decor preservation + overlap guard**

In `skill_assets/scripts/kpi_renderer.py`, just before `def clean_slide_to_blank` (line 164), add the content-zone constant and an overlap helper:

```python
# D4 (2026-06-06): the active content zone (px → EMU). A decorative pic that
# intersects this rectangle would collide with rendered content, so it is
# removed even when keep_decor is on; pics fully outside (corners/edges) stay.
_EMU_PER_PX = 9525
CONTENT_ZONE_PX = (35, 120, 1245, 660)  # left, top, right, bottom
CONTENT_ZONE_EMU = tuple(v * _EMU_PER_PX for v in CONTENT_ZONE_PX)


def _pic_overlaps_content(child) -> bool:
    """True if a <p:pic> element's bbox intersects CONTENT_ZONE_EMU. Missing
    geometry → treat as overlapping (conservative: strip it)."""
    xfrm = child.find(qn("p:spPr") + "/" + qn("a:xfrm")) if False else None
    # python-pptx-free XML walk: p:pic/p:spPr/a:xfrm/{a:off,a:ext}
    spPr = child.find(qn("p:spPr"))
    if spPr is None:
        return True
    xfrm = spPr.find(qn("a:xfrm"))
    if xfrm is None:
        return True
    off = xfrm.find(qn("a:off"))
    ext = xfrm.find(qn("a:ext"))
    if off is None or ext is None:
        return True
    try:
        x = int(off.get("x")); y = int(off.get("y"))
        cx = int(ext.get("cx")); cy = int(ext.get("cy"))
    except (TypeError, ValueError):
        return True
    l, t, r, b = CONTENT_ZONE_EMU
    return not (x + cx <= l or x >= r or y + cy <= t or y >= b)
```

Then change the `clean_slide_to_blank` signature and the `pic` handling. Replace lines 164–184 (the whole function body) with:

```python
def clean_slide_to_blank(slide, keep_title=True, keep_decor=False):
    """Удалить все shapes на slide, КРОМЕ title-placeholder шаблона (если
    keep_title). При keep_decor=True декоративные <p:pic> вне контент-зоны
    сохраняются (D4 reclaim), а пересекающие контент-зону — удаляются.
    Layout-inherited (logo, footer) останутся."""
    spTree = slide.shapes._spTree
    to_remove = []
    for child in list(spTree):
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag in ('sp', 'pic', 'graphicFrame', 'cxnSp', 'grpSp'):
            if keep_title and tag == 'sp' and _is_title_placeholder(child):
                txBody = child.find(qn('p:txBody'))
                if txBody is not None:
                    for p_el in txBody.findall(qn('a:p')):
                        for r_el in p_el.findall(qn('a:r')):
                            p_el.remove(r_el)
                continue
            if keep_decor and tag == 'pic' and not _pic_overlaps_content(child):
                continue
            to_remove.append(child)
    for el in to_remove:
        spTree.remove(el)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_clean_slide_decor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run renderer regression (default behavior unchanged)**

Run: `python -m pytest tests/unit/test_kpi_inline_layout.py tests/unit/test_chart_editorial.py -v`
Expected: PASS — these call `clean_slide_to_blank(slide)` with the default `keep_decor=False`, so behavior is identical to before.

- [ ] **Step 6: Commit**

```bash
git add skill_assets/scripts/kpi_renderer.py tests/unit/test_clean_slide_decor.py
git commit -m "$(cat <<'EOF'
D4 part 1: preserve template decor pics outside the content zone

clean_slide_to_blank gains keep_decor: keeps decorative <p:pic> that sit
outside the active content rectangle, strips ones that would overlap.
Default stays keep_decor=False so existing callers are unchanged.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: D4 part 2 — vertically center short card_grid content

**Files:**
- Modify: `skill_assets/scripts/flow_renderer.py:927-999` (`render_card_grid`)
- Test: `tests/unit/test_card_grid_centering.py`

**Design:** When a card grid is short (few rows), the bottom half is empty. Compute the grid's natural height and, when it is shorter than the available safe-area height, offset `top` down by half the slack so the grid is vertically centered. Tall/full grids are unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_card_grid_centering.py`:

```python
"""D4 part 2: short card grids are vertically centered in the safe area."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402

from flow_renderer import render_card_grid, SAFE_TOP, SAFE_BOTTOM  # noqa: E402

_PX = 9525


def _blank_slide():
    prs = Presentation()
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    return prs.slides.add_slide(layout)


def _topmost_panel_top_px(slide):
    tops = [round(s.top / _PX) for s in slide.shapes
            if s.shape_type == 1]  # AUTO_SHAPE (panel rects)
    return min(tops) if tops else None


def test_two_cards_are_centered():
    slide = _blank_slide()
    render_card_grid(slide, {"cols": 2, "cards": [
        {"title": "A", "text": "short"}, {"title": "B", "text": "short"}]})
    top = _topmost_panel_top_px(slide)
    # A single-row grid (height ~one row) must be pushed below SAFE_TOP so the
    # remaining vertical slack is split above and below.
    assert top is not None
    assert top > SAFE_TOP + 20


def test_full_grid_starts_at_safe_top():
    slide = _blank_slide()
    cards = [{"title": str(i), "text": "x"} for i in range(8)]  # 4 rows × 2
    render_card_grid(slide, {"cols": 2, "cards": cards})
    top = _topmost_panel_top_px(slide)
    # A full grid fills the area — no meaningful centering offset.
    assert top is not None
    assert abs(top - SAFE_TOP) <= 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_card_grid_centering.py -v`
Expected: FAIL — `test_two_cards_are_centered` fails (grid currently starts at SAFE_TOP regardless of fill).

- [ ] **Step 3: Implement vertical centering**

In `skill_assets/scripts/flow_renderer.py`, inside `render_card_grid`, after `ch = int((avail_h - (n_rows - 1) * gap) / n_rows)` (line 948), add:

```python
    # D4 part 2 (2026-06-06): center a short grid vertically — when the grid's
    # natural height (capped row height) leaves slack, push it down by half so
    # the bottom half isn't empty. Recompute ch from a sane max row height.
    if not cfg.get("content_top"):  # only when caller didn't pin the top
        max_ch = cfg.get("max_row_height", 230)
        if ch > max_ch:
            ch = max_ch
            used_h = n_rows * ch + (n_rows - 1) * gap
            slack = avail_h - used_h
            if slack > 0:
                top = top + slack // 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_card_grid_centering.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skill_assets/scripts/flow_renderer.py tests/unit/test_card_grid_centering.py
git commit -m "$(cat <<'EOF'
D4 part 2: vertically center short card grids

Cap card row height and split the leftover vertical slack so short
2/4-block grids no longer leave the bottom half empty.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: D5 — Screenshot browser-chrome frame

**Files:**
- Modify: `skill_assets/scripts/image_renderer.py:27-123` (`render_image_native`)
- Test: `tests/unit/test_image_screenshot_frame.py`

**Design:** When `image_config["frame"] == "browser"` (or `subcategory` indicates a screenshot), wrap the picture in brand browser-chrome: a green title-bar strip + a thin window outline around the picture (template slide 73). Plain `image_native` (photos/illustrations) is unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_image_screenshot_frame.py`:

```python
"""D5: screenshot images get a brand browser-chrome frame."""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()
from pptx import Presentation  # noqa: E402

from image_renderer import render_image_native  # noqa: E402


def _png(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.png"
    Image.new("RGB", (1200, 700), (240, 240, 240)).save(p)
    return str(p)


def _blank_slide():
    prs = Presentation()
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    return prs.slides.add_slide(layout)


def _green_strips(slide):
    from pptx.dml.color import RGBColor
    out = []
    for s in slide.shapes:
        if s.shape_type != 1:  # AUTO_SHAPE
            continue
        try:
            if s.fill.type is not None and s.fill.fore_color.rgb == RGBColor(0x26, 0xD0, 0x7C):
                out.append(s)
        except Exception:
            pass
    return out


def test_screenshot_adds_green_titlebar(tmp_path):
    slide = _blank_slide()
    render_image_native(slide, {
        "title": "Консоль управления",
        "image_path": _png(tmp_path),
        "frame": "browser",
    })
    assert len(_green_strips(slide)) >= 1
    # Picture is still present.
    assert any(s.shape_type == 13 for s in slide.shapes)  # PICTURE


def test_plain_image_has_no_chrome(tmp_path):
    slide = _blank_slide()
    render_image_native(slide, {
        "title": "Фото офиса",
        "image_path": _png(tmp_path),
    })
    assert len(_green_strips(slide)) == 0
    assert any(s.shape_type == 13 for s in slide.shapes)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_image_screenshot_frame.py -v`
Expected: FAIL — `test_screenshot_adds_green_titlebar` finds 0 green strips.

- [ ] **Step 3: Implement the browser-chrome frame**

In `skill_assets/scripts/image_renderer.py`, add a helper above `render_image_native` (before line 27):

```python
def _draw_browser_chrome(slide, x_px, y_px, w_px, h_px):
    """Brand browser-chrome around a screenshot: green title-bar strip on top +
    thin window outline. Coordinates are the PICTURE's placement (px)."""
    from pptx.enum.shapes import MSO_SHAPE
    BAR_H = 28
    # Green title bar strip above the picture.
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Emu((x_px) * EMU), Emu((y_px - BAR_H) * EMU),
        Emu(w_px * EMU), Emu(BAR_H * EMU))
    bar.fill.solid()
    bar.fill.fore_color.rgb = GREEN
    bar.line.fill.background()
    # Thin window outline around the picture (transparent fill, green line).
    outline = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Emu(x_px * EMU), Emu(y_px * EMU),
        Emu(w_px * EMU), Emu(h_px * EMU))
    outline.fill.background()
    outline.line.color.rgb = GREEN
    outline.line.width = Pt(1.5)
    return bar, outline
```

Then, in `render_image_native`, after the `slide.shapes.add_picture(...)` call (lines 99–103), add:

```python
    # D5 (2026-06-06): screenshot chrome — green title bar + window outline.
    subcat = str(image_config.get("subcategory", ""))
    is_shot = image_config.get("frame") == "browser" or subcat.startswith("screenshot")
    if is_shot:
        _draw_browser_chrome(slide, final_x, final_y, final_w, final_h)
```

(`GREEN`, `Pt`, `EMU` are already imported at the top of the module: `GREEN` from `kpi_renderer`, `Pt` from `pptx.util`, `EMU = 9525` at line 24.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_image_screenshot_frame.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add skill_assets/scripts/image_renderer.py tests/unit/test_image_screenshot_frame.py
git commit -m "$(cat <<'EOF'
D5: browser-chrome frame for screenshot images

Wrap screenshot pictures (frame="browser" / subcategory screenshot) in a
green title-bar strip + window outline (template slide 73). Plain photos
are unchanged.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Prompt wiring (Agent 02 chart.style + screenshot; Agent 03 phrase markup)

**Files:**
- Modify: `llm/prompts/agent_02_slide_classifier.py`
- Modify: `llm/prompts/agent_03_content_distributor.py`

**Design:** No new tests (prompt text is validated by the live runs in Task 8). Three additive rules:
1. Agent 02 sets `chart.style="editorial"` for **single-series** "hero" growth/impact bar charts.
2. Agent 02 sets `image.frame="browser"` (and keeps `subcategory` screenshot) for UI/screenshot images.
3. Agent 03 marks ONE key phrase per body paragraph with `**…**`.

- [ ] **Step 1: Add the chart.style + screenshot rules to Agent 02**

In `llm/prompts/agent_02_slide_classifier.py`, in the `chart` schema description inside `SYSTEM` (line 32, the `chart: {{...}}` field), append `style` to the inline schema:

```python
      chart: {{type: "area_stacked"|"area_100"|"bar"|"bar_stacked"|"line"|"pie", style: "editorial"|null, title: string, caption: string, x: any[], series: [{{name: string, data: number[]}}], accent_idx: number}} | null,
```

Then in the `image` schema field (line 34, `image: {{...}}`), add `frame`:

```python
      image: {{title: string, image_path: string, caption: string, subcategory: string, frame: "browser"|null}} | null,
```

After the chart trigger line (line 60, `- Серии данных с осью → chart_pptx_native ...`), add:

```python
- chart.style="editorial" ТОЛЬКО для ОДНОСЕРИЙНОГО bar-чарта, который является «героем» роста/импакта (одна метрика по годам/категориям, есть пиковое значение). Многосерийные и не-bar чарты → style=null (чистый светлый чарт). accent_idx = индекс пикового/ключевого столбца.
```

After the image classification line (line 54, `- image (UI/скриншот) → ...`), add:

```python
- Для UI/скриншота проставь image.frame="browser" (рендер добавит бренд-хром: зелёная title-плашка + рамка окна, эталон slide 73). Обычное фото/иллюстрация → frame=null.
```

- [ ] **Step 2: Add the phrase-markup rule to Agent 03**

Read `llm/prompts/agent_03_content_distributor.py` first to locate the body-fill section, then add (near the body/slot-fill rules) a rule with the exact `**…**` contract:

```python
# Append to the SYSTEM prompt's body-styling rules:
- ВЫДЕЛЕНИЕ КЛЮЧЕВОЙ ФРАЗЫ: в каждом абзаце body можешь пометить ОДНУ ключевую фразу (≤6 слов) разметкой **…** — финальный пас сделает её зелёной+полужирной (эталон slide 28). НЕ помечай числа (они подсвечиваются автоматически), НЕ помечай больше одной фразы на абзац, НЕ ставь ** на тёмных слайдах (там разметка просто срезается). Если выделять нечего — не ставь разметку.
```

(Place this verbatim string into the existing system-prompt f-string at the body-rules location identified by reading the file.)

- [ ] **Step 3: Smoke-import both prompt modules**

Run: `python -c "import llm.prompts.agent_02_slide_classifier as a2, llm.prompts.agent_03_content_distributor as a3; print('SYSTEM' in dir(a2) or hasattr(a2,'SYSTEM')); print('imports OK')"`
Expected: `imports OK` (no f-string/syntax errors from the new `{{…}}` text)

- [ ] **Step 4: Commit**

```bash
git add llm/prompts/agent_02_slide_classifier.py llm/prompts/agent_03_content_distributor.py
git commit -m "$(cat <<'EOF'
D1/D2/D5 wiring: chart.style=editorial, image.frame=browser, **phrase**

Agent 02 emits editorial style for single-series hero bar charts and a
browser frame for screenshots; Agent 03 marks one key phrase per body
paragraph with **…** for inline emphasis.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full 5-deck live validation + before/after vs template

**Files:**
- Create: `tmp/p11/make_deck_d.py` (screenshots → D5)
- Create: `tmp/p11/make_deck_e.py` (editorial chart + inline phrase → D1+D2)
- Existing: `tmp/p11/make_feature_deck.py` (A), `make_deck_b.py` (B), `make_deck_c.py` (C)

**Design:** Exercise all D1–D5 across 5 decks against real Cloud.ru, render PNGs in the worker container, and produce before/after comparisons vs template reference slides (43 KPI, 47 chart, 28 phrase, 73 screenshot).

- [ ] **Step 1: Create deck D (screenshots — D5)**

Create `tmp/p11/make_deck_d.py`:

```python
"""Deck D — screenshot-heavy: exercises D5 browser-chrome frame."""
from __future__ import annotations
import sys
from pathlib import Path
from pptx import Presentation


def build(out: Path) -> Path:
    prs = Presentation()
    title_l = prs.slide_layouts[0]
    bullet = prs.slide_layouts[1]

    s = prs.slides.add_slide(title_l)
    s.shapes.title.text = "Обзор интерфейса платформы"
    s.placeholders[1].text = "Скриншоты ключевых экранов консоли"

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Главная консоль управления"
    s.placeholders[1].text_frame.text = (
        "Скриншот: единая панель мониторинга ресурсов, виджеты нагрузки, "
        "статусы сервисов и быстрые действия в одном окне")

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Экран биллинга"
    s.placeholders[1].text_frame.text = (
        "Скриншот интерфейса биллинга: детализация по сервисам, прогноз "
        "расходов и история платежей")

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Возможности платформы"
    tf = s.placeholders[1].text_frame
    tf.text = "Автомасштабирование. Ресурсы растут под нагрузку автоматически"
    for line in [
        "Мониторинг. Метрики и алерты из коробки",
        "Резервные копии. Снапшоты по расписанию",
        "Доступ. Гранулярные роли и политики IAM",
    ]:
        p = tf.add_paragraph(); p.text = line

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Начните бесплатно"
    s.placeholders[1].text_frame.text = "Регистрация на cloud.ru"

    prs.save(str(out))
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "deck_d.pptx")
    p = build(out)
    print(f"wrote {p} ({len(Presentation(str(p)).slides._sldIdLst)} slides)")
```

- [ ] **Step 2: Create deck E (editorial chart + inline phrase — D1+D2)**

Create `tmp/p11/make_deck_e.py`:

```python
"""Deck E — editorial growth chart + phrase-emphasis body: exercises D1 + D2."""
from __future__ import annotations
import sys
from pathlib import Path
from pptx import Presentation


def build(out: Path) -> Path:
    prs = Presentation()
    title_l = prs.slide_layouts[0]
    bullet = prs.slide_layouts[1]

    s = prs.slides.add_slide(title_l)
    s.shapes.title.text = "Рост платформы за 4 года"
    s.placeholders[1].text = "Ключевые показатели и динамика"

    # Single-metric growth → editorial bar chart (D1).
    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Число клиентов растёт кратно"
    tf = s.placeholders[1].text_frame
    tf.text = "2023: 120 клиентов"
    for line in ["2024: 340 клиентов", "2025: 720 клиентов", "2026: 1280 клиентов"]:
        p = tf.add_paragraph(); p.text = line

    # Two-column body with a key phrase to emphasize (D2).
    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Почему выбирают нас"
    tf = s.placeholders[1].text_frame
    tf.text = ("Платформа обеспечивает полную изоляцию данных каждого клиента "
               "и сертифицированную защиту по 152-ФЗ")
    for line in [
        "Команда поддержки на связи круглосуточно без выходных",
        "Миграция с других облаков выполняется бесплатно за счёт провайдера",
    ]:
        p = tf.add_paragraph(); p.text = line

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Платформа в цифрах"
    tf = s.placeholders[1].text_frame
    tf.text = "99.95% — доступность сервисов"
    for line in ["1280 — корпоративных клиентов", "6 — регионов"]:
        p = tf.add_paragraph(); p.text = line

    s = prs.slides.add_slide(bullet)
    s.shapes.title.text = "Начните сегодня"
    s.placeholders[1].text_frame.text = "cloud.ru — грант на тестирование"

    prs.save(str(out))
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "deck_e.pptx")
    p = build(out)
    print(f"wrote {p} ({len(Presentation(str(p)).slides._sldIdLst)} slides)")
```

- [ ] **Step 3: Build the 5 source decks**

Run:
```bash
cd "C:/Users/Глеб/Documents/Slides_bot" && \
python tmp/p11/make_feature_deck.py tmp/p11/deck_a.pptx && \
python tmp/p11/make_deck_b.py tmp/p11/deck_b.pptx && \
python tmp/p11/make_deck_c.py tmp/p11/deck_c.pptx && \
python tmp/p11/make_deck_d.py tmp/p11/deck_d.pptx && \
python tmp/p11/make_deck_e.py tmp/p11/deck_e.pptx
```
Expected: five `wrote …` lines.

- [ ] **Step 4: Run the live pipeline on all 5 decks (real Cloud.ru calls)**

For each deck (a–e), run the host pipeline (soffice soft-fails on host; result.pptx lands in `%TEMP%/slidesbot/<session>/`):
```bash
for d in a b c d e; do \
  LIVE_RUN_INPUT="tmp/p11/deck_${d}.pptx" python -m scripts.live_run 2>&1 | tee "tmp/p11/live_${d}.log"; \
done
```
Expected: each run completes through `finalize`; capture each `<session>` id and the result.pptx path from the log. If Agent 06 emits a pydantic ValidationError (known intermittent `height_emu`/`top_emu`), re-run that single deck once.

- [ ] **Step 5: Render every result deck to PNGs in the worker container**

For each session's `result.pptx` (path from Step 4 logs), render in `slides-bot-worker`:
```bash
# Replace <SESS> and <SRC> per deck from the live logs.
docker cp "<SRC>/result.pptx" slides-bot-worker:/tmp/deck_<d>.pptx
docker exec slides-bot-worker python /app/skill_assets/scripts/render_slides.py /tmp/deck_<d>.pptx /tmp/out_<d>/
docker cp slides-bot-worker:/tmp/out_<d>/. tmp/p11/render_<d>_pngs/
```
Expected: per-slide PNGs under `tmp/p11/render_<d>_pngs/`.

- [ ] **Step 6: Visual-verify against the 4 reference template slides**

Read these PNGs with the Read tool and confirm each target pattern landed:
- **D3 (KPI, ref slide 43):** deck C slide "Платформа в цифрах" + deck E "Платформа в цифрах" — number-left / desc-right inline, enlarged `%`, graphite numbers, green underline plate on the accent.
- **D1 (chart, ref slide 47):** deck E "Число клиентов растёт кратно" — dark slide, graduated green bars (peak brightest), large white peak number overlay; chart still selectable/editable.
- **D2 (phrase, ref slide 28):** deck E "Почему выбирают нас" — exactly one green bold phrase ("полную изоляцию данных") on the light slide; no literal `**`.
- **D5 (screenshot, ref slide 73):** deck D "Главная консоль управления" / "Экран биллинга" — green title-bar strip + window outline around the image.
- **D4:** any native KPI/chart deck — corner decor preserved if present; short card grids vertically centered (no empty bottom half).

Note any defect (wrong routing, overflow, color clash, doubled `%`, green-on-dark) for a follow-up fix batch.

- [ ] **Step 7: Build before/after contact sheets in the worker (PIL)**

Pair each new render against the prior committed render (run7/run8 PNGs in `tmp/p11/`) and the template reference. Use the existing PIL contact-sheet approach in the worker container (no ImageMagick) to emit `tmp/p11/phaseD_before_after.png`. Confirm the sheet renders and visually shows the improvement per D1/D2/D3/D5.

- [ ] **Step 8: Regression watch (must all hold)**

Run the full unit suite + confirm chart editability + no doubled `%`:
```bash
python -m pytest tests/unit/test_kpi_emphasis.py tests/unit/test_kpi_inline_layout.py tests/unit/test_chart_editorial.py tests/unit/test_clean_slide_decor.py tests/unit/test_card_grid_centering.py tests/unit/test_image_screenshot_frame.py tests/unit/test_enforce_canonical.py -v
```
Expected: all PASS. In the rendered decks confirm: editorial chart opens in PowerPoint → Edit Data (native object present in Step 5 PNG had real bars); KPI `%` never doubled; no green text on light beyond the one intended phrase per paragraph.

- [ ] **Step 9: Commit the test decks + record findings**

```bash
git add tmp/p11/make_deck_d.py tmp/p11/make_deck_e.py
git commit -m "$(cat <<'EOF'
Phase D validation: deck D (screenshots) + deck E (editorial+phrase)

Two new live-validation decks so D1–D5 are all exercised across 5 decks.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

Update memory file `memory/diversity_batch_2026_06_05.md` (or a new `memory/phase_d_2026_06_06.md` indexed in `MEMORY.md`) with: which decks exercised which feature, any non-obvious routing/render facts, and any deferred defects — only the surprising/non-obvious parts.

---

## Self-Review

**Spec coverage:**
- D1 editorial chart → Task 3 (+ trigger in Task 7). ✓
- D2 inline phrase emphasis → Task 1 (+ Agent 03 markup in Task 7). ✓
- D3 KPI inline layout → Task 2. ✓
- D4 part 1 reclaim decor → Task 4; part 2 center content → Task 5. ✓
- D5 screenshot frame → Task 6 (+ trigger in Task 7). ✓
- Locked decisions honored: KPI numbers stay graphite (Task 2 sets `color = text_color`, accent only via `_add_accent_bar`); D4 sources no new assets (only preserves existing pics). ✓
- Validation (unit + 5-deck live + before/after vs slides 43/47/28/73) → Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `emphasize_phrases_in_slide(slide, *, emphasis_hex)` used identically in tests, impl, and `apply_kpi_emphasis`. `is_editorial_eligible`/`_green_ramp` names match across impl and `test_chart_editorial.py`. `clean_slide_to_blank(slide, keep_title, keep_decor)` + `CONTENT_ZONE_EMU` match between `kpi_renderer.py` and `test_clean_slide_decor.py`. `_draw_browser_chrome` private to `image_renderer.py`. ✓

**Note for the executor:** Agent 03's prompt file (`llm/prompts/agent_03_content_distributor.py`) must be READ before Task 7 Step 2 to place the `**…**` rule at the correct location in its system f-string — the exact insertion line is not pinned here because the file was not read during planning.
