# Layout Quality & Visual Diversity — Phased Design

**Date:** 2026-06-05
**Goal (user):** Significantly improve how the LLM assembles decks — (1) layout/verstka
quality, (2) context-aware donor selection, (3) charts/diagrams/tables assembly,
(4) much greater visual diversity.
**Approved approach:** Approach A — foundation-first, phased.

## Problem statement

Post-audit, the pipeline produced monotonous decks with two structural defects:

1. **Dense donors 33 (6-block) and 35 (8-block) were unfillable.** Their
   `donor-slot-map.yaml` entries declared only a `title` slot (sub/body slots were
   `TODO` stubs). Any 6/8-block slide routed there could fill only the title →
   empty slides + content loss. Their template mock cells ("Подзаголовок в две
   строки 20pt") leaked because they weren't slot-mapped.
2. **The 4 rich `flow_renderer` presets (`card_grid`, `numbered_rows`,
   `numbered_columns`, `hero_statement`) were unreachable from the LLM pipeline.**
   No agent emitted `flow.preset`, and `_native_block_is_usable` rejected any flow
   block without a `blocks` list. So every "comparison/process/value" slide fell
   back to donor clones — visually repetitive.

Agent 04 (Layout Designer) had also been reduced to a pure router, losing the
original skill's density limits, fit reasoning, and image context test.

## Phases

### Phase 1.1 — Complete donors 33/35 slot maps (DONE, validated)
- Inspected template slides 33/35; mapped `shape_idx` for every subtitle (BODY-type,
  H=53, top of each block) and body box (OBJECT-type, H~156, below).
- Donor 33: title=0; sub1..6 = 7,8,9,10,11,12; body1..6 = 1,2,5,3,4,6 (reading
  order TL,TM,TR,BL,BM,BR). Donor 35: title=0; sub1..8 = 9..16; body1..8 =
  1,2,5,7,3,4,6,8.
- Subtitles 20pt bold black (canonical), max_chars 30/safe 22. Bodies 14pt,
  33: max 160/safe 120, 35 (narrower frames): max 120/safe 90.
- Added `content_6subtitles: [33]` / `content_8subtitles: [35]` to
  `category_equivalence` so the `6block`/`8block` subcat overrides resolve.
- **Validated:** rendered both donors fully populated + correct reading order;
  sparse title-only case still produces a clean frame (F1b WIPE + standard
  slot-clearing now cover the mock cells — a positive interaction).
- Known minor artifact: donor 33 sub2 inherits a green accent highlight from the
  layout placeholder (template design, not introduced by this change).

### Phase 1.2/1.3 — Pipeline support for presets + under-fill (DONE)
- `_native_block_is_usable` (pipeline.py): flow slides with a known `preset`
  (`card_grid`→cards, `numbered_rows`→rows, `numbered_columns`→columns,
  `hero_statement`→statement) are buildable when the preset's data key is present.
  Blocks-mode path unchanged.
- `_sanitize_native_block`: returns early for preset flow blocks (don't force
  `grid=true`; the renderer dispatches to the preset and returns before the grid
  path).
- **Under-fill guardrail decision:** NOT adding an assemble-time donor re-route.
  build_v9 already renders sparse structural donors as a clean title-only frame,
  and the real fix is upstream (working 33/35 + native presets). A re-route would
  be speculative (content is already distributed against donor slots) and risky.

### Phase 3a — Agent 02 emits flow presets (DONE)
- Extended the classifier `flow` block schema with `preset` + `cards`/`columns`/
  `rows`/`statement`/`support`.
- Added a "NATIVE FLOW-ПРЕСЕТЫ" routing section: 4–8 parallel "title+desc" blocks
  → `card_grid`; 3–5 ordered steps → `numbered_columns`; 6–8 ordered items →
  `numbered_rows`; single punchy value statement → `hero_statement`; genuine
  connected schemas keep blocks+arrows. Plain unstructured lists stay on the
  multicolumn donor route.
- Reconciled the comparison intent→category mapping to prefer the native preset,
  with donor 33/35 as fallback.
- chart_pptx_native / table_native / kpi_native triggers were already present and
  are retained (charts/tables/KPI diversity).

### Phase 2 — Restore Agent 04 designer intelligence (DONE)
- Added density→column-count thresholds (2col ≤45w, 3col ≤35w, 4block ≤25w,
  6block ≤20w, 8block ≤15w) — too-dense content picks a roomier donor or defers to
  the native preset.
- Added the image context test ("if you remove the image, does the slide lose
  meaning?") to avoid decorative image donors.
- Sharpened the overflow strategy (roomier donor → re-split → shrink ≥12pt →
  native preset fallback).

## Validation
- Unit: preset usability/sanitize logic; build_v9 renders all 4 presets + donors
  33/35 at production quality (manual PNG review in worker LibreOffice).
- Offline e2e pipeline test passes.
- Live: real Cloud.ru run on a 7-slide Russian feature deck (title, 6-cap card_grid,
  4-step process, value statement, revenue chart, tariff table, KPI), built pptx
  rendered + reviewed against the brand template.

### Phase 4 — Live-render defect fix (DONE)
- Live run (session 5e2c956615fc498e, 7-slide feature deck) routed exactly as
  designed: card_grid, numbered_columns, hero_statement, chart_pptx_native,
  table_native, kpi_native. 6/7 slides production quality on first render.
- **Defect found + fixed:** kpi_native slide rendered a doubled, overflowing `%`
  when an LLM value carried a trailing `%` (e.g. `"99.97%"`) *and* `pct=true` —
  the inline `%` wrapped the 100pt frame to a second line and collided with the
  `pct` superscript. Fixed defensively in `kpi_renderer.render_kpi`: strip a
  trailing `%` from the value and route it through the `pct` superscript. This is
  a boundary-normalize against untrusted LLM output, robust regardless of which
  agent emits the stray `%`. Re-rendered clean; 19 kpi unit tests pass.

## Out of scope / follow-ups
- enforce_canonical converts preset green accent numbers (numbered_columns) to
  graphite under the "no green text on light" rule — acceptable, noted.
- Agent 06 raw-EMU overlay path is unchanged; preset diversity is driven through
  the flow_diagram_native native route instead.
- Title-slide subtitle overflow on very short titles: a 1-word title (e.g.
  "Cloud.ru") autofits huge on donor 4 and pushes the subtitle placeholder low
  enough that a 3-line wrap clips the footer. Pre-existing donor-4 title-autofit
  edge, orthogonal to this batch — not addressed here.
