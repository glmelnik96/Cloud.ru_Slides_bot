# Image-Slide Reconstruction — Design Spec

**Date:** 2026-06-06
**Status:** Approved (design sections 1–4 confirmed by user)
**Topic:** Recover the visual/"image-only" slides the pipeline currently drops, by reconstructing structured diagrams into native brand layouts and falling back to a full-bleed render for the rest.

---

## 1. Problem

When a `.pptx` slide carries its content inside grouped shapes or as pure vector graphics, the pipeline drops it. On the `dl2` deck (Воркшоп, 36 slides), **16 of 36 slides are dropped** for this reason.

**Root cause (confirmed in code):** `parse_pptx.parse` iterates only `slide.shapes` (top-level) and never recurses into `GROUP` shapes. Pictures nested in groups are also missed. As a result the brief/classifier nodes see an empty "visual" slide → mark `intent=image` → `image_native` with no `image_path` → `assemble_plan_node` skips it (`_native_block_is_usable` returns False because `image_path`/`path` is absent).

**Empirical breakdown of the 16 dropped `dl2` slides** (verified with `extract_images.py` + recursive group walk):

- **Slide 9** — has an embedded raster (1149×535 PNG). Recoverable via raster extraction.
- **Slide 8** — group contains a structured numbered list (узлы "1…5" + подписи "ТАРИФИКАЦИЯ ПО ТОКЕНАМ" и т.д.). Recoverable as a native diagram.
- **Slides 11, 31, and others** — groups contain only primitives (lines/shapes) with **no text**. Nothing to reconstruct; only a full-slide render recovers them.

So a single approach is insufficient: extraction recovers ~1/16, reconstruction recovers the structured subset, and a render fallback is required to lose zero slides.

## 2. Goal & Non-Goals

**Goal:** No visual slide is silently dropped. Where structure exists, rebuild it as a native brand layout (not an image). Otherwise place the original content as an image on a branded layout.

**Non-Goals:**
- No changes to `build_v9` core, `donor-slot-map.yaml`, or the table/kpi/chart native paths.
- No OCR or vector-to-shape vectorization of opaque graphics — those are rendered as-is.
- No new renderers — `flow_renderer` (C) and `image_renderer` (A/B) already exist and are validated.

## 3. Target Data Flow

```
parse_node (parse_pptx)
   ├─ NEW: recursive group walk → collect nested text + geometry + pictures
   ├─ NEW: visual_kind classification per slide:
   │        none | structured | raster | opaque
   ├─ NEW (media_prep):
   │        raster  → extract_images → image_path (largest raster on slide)
   │        opaque  → render slide to PNG (LibreOffice) → image_path
   └─ NEW: extend grounding PNGs from "slide 1 only" to ALL visual slides
            (so Kimi vision actually sees the diagram)

classify / distribute (agents 02/03)
   ├─ structured  → flow_diagram_native (preset: numbered_rows / card_grid / …)
   └─ raster|opaque → image_native (image_path already present)

assemble_plan_node   — unchanged logic; image_path now present so no skip
build_v9             — flow_renderer (C) / image_renderer (A/B), wiring only
```

**Fallback chain (a slide is never lost in production):**
`C (reconstruct)` → on failure `B (full-bleed render)` → only if soffice absent `drop + explicit WARN`. In the worker container soffice is present, so the production floor is B.

## 4. Components (isolated units)

### 4.1 `parse_pptx._walk_shapes(shapes)` — NEW, pure function
Flattens the shape tree, recursing into `GROUP`. Returns `list[LeafShape]` with `(shape_type, text, left/top/width/height in emu, depth)`. No dependencies beyond python-pptx. Independently testable on a synthetic pptx.

### 4.2 `parse_pptx.parse` — MODIFIED
Uses `_walk_shapes` instead of the direct top-level loop. Group text → `body`/`text_runs`; group pictures → `images`. Adds per-slide fields:
- `visual_kind: "none" | "structured" | "raster" | "opaque"`
- `group_nodes: [{text, left, top, w, h, order}]` (structured nodes, for the classifier to map into a preset)

Boundary: parsing only — no intent classification, no rendering.

### 4.3 `classify_visual_kind(slide_data)` — NEW, pure function
Deterministic (not LLM):
- `raster` — a picture with area ≥ `RASTER_MIN_AREA_PX`.
- `structured` — ≥ `STRUCTURED_MIN_NODES` text nodes in groups AND a numeric/marker sequence or a regular coordinate grid, capped at `STRUCTURED_MAX_NODES`.
- `opaque` — visual slide matching neither.
- `none` — ordinary text slide (feature does not intervene).

Returns one class. Testable on fixtures.

### 4.4 `media_prep` in `parse_node` — NEW, orchestration
- `raster` → `extract_images.extract()` → largest raster on slide → `image_path`.
- `opaque` → render that single slide to PNG via soffice (same mechanism already used for slide 1) → `image_path`.
- Stores paths into `parsed_deck`; extends `original_pngs` to all visual slides.

Boundary: file preparation only; layout decision belongs to the agents.

### 4.5 Agent 02/03 prompts — MODIFIED
- Classifier: `structured` + `group_nodes` → choose `flow_diagram_native` with the fitting preset, mapping nodes into `cards`/`rows`. `raster`/`opaque` → `image_native` (image_path already in data).
- Prompts are re-engineered for the target model (not Claude-tuned), per project rule.

### 4.6 Renderers — UNCHANGED
`flow_renderer` (C) and `image_renderer` (A/B) already exist and are validated. Verify only that `assemble_plan_node` forwards `image_path`/`flow` correctly.

**Not touched:** build_v9 core, donor-slot-map, table/kpi/chart paths.

## 5. Routing Logic, Thresholds, Errors

**Decision tree** (in `classify_visual_kind`):
```
slide after recursive parse
├─ has normal text content (title+body)?  → YES → ordinary path (feature inert)
└─ visual slide:
     ├─ structured: ≥3 group text nodes + sequence/grid  → flow_diagram_native (C)
     │      └─ reconstruction fails → B
     ├─ raster: picture area ≥ threshold                 → image_native + raster (A)
     │      └─ extract fails → B
     └─ opaque: no structure, no raster                  → image_native + full-bleed (B)
```

**Named thresholds (constants, no magic numbers):**
- `RASTER_MIN_AREA_PX = 200 * 200` — smaller treated as icon/logo, not content.
- `STRUCTURED_MIN_NODES = 3` — fewer is not a diagram (→ opaque/B).
- `STRUCTURED_MAX_NODES = 8` — more does not fit presets cleanly → B (full render more reliable than a poor reconstruction).

**Error handling (each level falls to the next; slide not lost):**
1. Recursive parse raises on a shape → catch, skip that shape, keep the slide (mirrors existing table-parse behavior).
2. `extract_images` yields no raster → switch to B.
3. soffice render unavailable (e.g. on host) → image_native without image_path → slide drops **but** logs explicit `WARN media_prep.no_soffice`. In the worker soffice exists, so this does not fire in prod.
4. Preset reconstruction fails (classifier cannot map nodes) → B.

**Observability:** per visual slide, log `visual_route slide=N kind=structured→flow|raster→image|opaque→image_b`.

## 6. Testing & Verification

**Unit tests (synthetic fixtures, no full pipeline):**
1. `test_walk_shapes_recurses_groups` — 2-level nested groups → all nested text + pictures extracted, depth correct.
2. `test_classify_visual_kind` — case table: structured / raster / opaque / none → expected class.
3. `test_media_prep_raster` — embedded png slide → `image_path` points at extracted file, area above threshold.
4. `test_media_prep_opaque_renders` — mock soffice → render invoked and path set for opaque; absent soffice → WARN, no crash.
5. `test_thresholds` — boundaries (2 nodes → not structured; 9 nodes → B; 100×100 icon → not raster).

**Existing tests must stay green:** `test_image_screenshot_frame`, `test_clean_slide_decor`, `test_pipeline_smoke`.

**Integration verification (real dl2 in worker):**
- Baseline: dl2 = 20 built / 16 dropped.
- Re-run grounded dl2; from logs confirm `visual_route` counts across C/A/B.
- **Target: 0 dropped** (floor is B).
- Visual check of key slides: 8 (structured → native numbered diagram, NOT an image), 9 (raster → clean insert), 11/31 (opaque → full-bleed render). Render output to PNG, compare against input slide and template.

**Definition of Done:**
- dl2: 36/36 slides in output (0 drops); structured slides genuinely rebuilt as brand layouts, not images.
- dl1/dl3 do not regress (re-run both, compare against current clean state).
- Unit tests green.
