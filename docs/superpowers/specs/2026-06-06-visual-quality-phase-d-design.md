# Visual Quality & Diversity — Phase D Design

**Date:** 2026-06-06
**Goal (user):** Close the gap between what the pipeline generates and the brand
template's full design vocabulary. After a 3-deck visual audit (input decks → our
render → the 88-slide Cloud.ru template), we use ~40% of the template's vocabulary.
This phase raises visual quality and diversity by adopting 5 reference patterns.
**Approved approach:** Approach A — phased, foundation-respecting. Full scope D1–D5.

## Context / audit findings

Comparing our live renders against template reference slides:
- **Slide 43 (KPI):** template uses number-left / description-right inline with a
  large attached `%`. Ours: number centered, description below, small `%`.
- **Slide 47 (chart):** template uses a dark editorial chart — graduated green bars
  (peak brightest) with a giant overlaid number. Ours: uniform green bars on white.
- **Slide 28 (2col):** template bolds+greens a key *phrase* inside body text. Ours:
  only numerics auto-green.
- **Slides 8/73 + isometric/gradient art:** template ships decorative 3D/abstract
  graphics; our native renders strip them and leave empty zones.

## Decisions locked before design

- **KPI number color stays graphite** (user canon 2026-05-29, re-confirmed
  2026-06-06). D3 is layout-only; accent remains the green underline-plate, not a
  green number.
- **D4 does NOT source a new isometric asset pack.** No such asset library exists in
  the repo; all current decor is code-generated shapes, and native renders strip the
  template's embedded pictures. D4 instead *reclaims* the template's own embedded
  decor + centers short content. New-asset sourcing is an explicit out-of-scope
  follow-up.

## Phases

### D1 — Editorial chart `[MEDIUM]`
**Current:** `skill_assets/scripts/chart_native_pptx.py` `add_chart_to_slide()` builds
an *editable* native PPTX chart. Color is per-series only (`_apply_series_colors`);
the native chart API does not expose per-bar fill or a background fill.

**Change:** add an `style: "editorial"` path for **single-series bar** charts:
1. Restructure the one series into N single-value series so each bar carries its own
   color → graduated green ramp (dark→bright), the `accent_idx` bar brightest
   (`#26D07C`). Multi-series charts keep the current uniform path.
2. Render on a **dark (graphite) slide** — set the slide/blank-donor background to
   dark and text/axis to white (the `dark` flag already threads through
   `chart_engine`/`chart_native_pptx`; the slide background is set at build time via
   the dark blank donor, as kpi_native already does).
3. Overlay a large **"выноска" number** (peak or total value) as a separate textbox
   to the right of the plot, white, ~150pt.

**Stays editable** (still a native chart object; bars are real data series).
**Trigger:** Agent 02 sets `chart.style="editorial"` for single-series bar charts
that are "hero" growth/impact charts; default stays the clean light chart.

### D2 — Inline green phrase emphasis `[EASY]`
**Current:** `skill_assets/scripts/kpi_emphasis.py` `_emphasize_paragraph()` already
splits a paragraph into runs to bold+green numeric tokens — the exact run-splitting
mechanism needed. Body slots are otherwise filled as a single run
(`replace_text_with_style`).

**Change:** generalize the emphasis pass to also emphasize **one key phrase per body
paragraph** (bold + green), matching template slide 28:
- Agent 03 (distributor) marks the phrase inline with `**…**` markup in the slot text.
- A new emphasis helper strips the markup and applies the existing run-split styling
  to the marked span. Reuses `kpi_emphasis`'s XML run-mutation, not a parallel impl.
- **Guardrails:** at most ONE emphasized phrase per paragraph; phrase length ≤ ~6
  words; if no markup present, no phrase emphasis (numeric auto-green unchanged).
  Skip on dark slides where green-on-dark would clash with the canon, and skip inside
  preset/native renders that have their own styling.

### D3 — KPI inline layout `[MEDIUM]`
**Current:** `skill_assets/scripts/kpi_renderer.py` `render_kpi()` — number centered
(`PP_ALIGN.CENTER`, `NUMBER_TOP=200`), description below (`DESC_TOP=470`), small `%`
top-right (`pct_size = max(40, NUMBER_FONT//3)`).

**Change:** restructure to **number-left / description-right inline** (template
slide 43):
- Number left-aligned in its column; description box placed to the right of the
  number's right edge, vertically centered to the number, ~12–16pt.
- Enlarge the attached `%` to ≈0.5× number height, kerned tight to the number's
  top-right.
- Pure geometry/constant refactor; **color stays graphite**; green underline-plate
  accent retained. Recompute column x/width for n=1/2/3 so number+desc pair fits.

### D4 — Reclaim template decor + center content `[HARD → de-risked]`
**Current:** `kpi_renderer.clean_slide_to_blank()` removes ALL shapes except the
title placeholder before every native render (kpi/chart/table/flow/image), stripping
the donor's embedded decorative pictures. `flow_renderer` only adds code-generated
diagonal arrows.

**Change (two parts):**
1. **Keep decorative pictures on native slides.** Make `clean_slide_to_blank` strip
   mock *text* shapes (and content placeholders) but **preserve `pic` shapes** that
   are template decoration (isometric/gradient art), so native preset/KPI/chart
   slides inherit real brand graphics. Add a guard so a decor pic never overlaps the
   content zone (if a pic intersects the active content area, still remove it).
2. **Vertically center short content** in card_grid and donor 33/35 blocks so the
   bottom half isn't empty when blocks are short (the empty-bottom seen on team-fix
   and 6-block renders).

**Explicitly out of scope:** sourcing/embedding a NEW isometric or gradient asset
pack. If reclaim+centering proves insufficient, that becomes its own follow-up spec.

### D5 — Screenshot frame `[EASY]`
**Current:** `skill_assets/scripts/image_renderer.py` `render_image_native()` places a
plain centered picture; no chrome.

**Change:** when `image.subcategory`/mode indicates a screenshot, wrap the picture in
the brand browser-chrome (template slide 73): green title-bar strip + thin window
outline + optional side caption box. Native shapes drawn around the existing picture
placement; plain `image_native` (photos/illustrations) is unchanged.

## Validation

- **Unit:** per-renderer checks — D1 editorial series-split + overlay; D2 phrase
  run-split (one phrase, markup stripped, dark-skip); D3 inline geometry math; D4
  decor-pic preservation + content-zone overlap guard + centering; D5 frame shapes.
  Re-run existing `test_kpi_emphasis.py` (must stay green).
- **Live:** re-run the same 3 decks (A: presets+natives, B: donor-route stress, C:
  dense blocks) against real Cloud.ru, render in the worker container, and produce
  **before/after** PNGs vs. the template reference slides (43, 47, 28, 73).
- **Regression watch:** chart editability preserved (open in PowerPoint → Edit Data);
  no green text on light beyond the intended phrase; KPI `%` not doubled (the
  2026-06-05 fix must still hold).

## Out of scope / follow-ups

- New isometric/gradient asset pack (D4 part 3) — separate spec if needed.
- Agent 06 raw-EMU overlay robustness (intermittent pydantic ValidationError on
  missing `height_emu`/`top_emu`) — orthogonal reliability fix, tracked separately.
- Donor-4 short-title autofit clipping the footer — pre-existing, untouched.
