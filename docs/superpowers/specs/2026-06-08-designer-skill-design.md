# Designer-from-Scratch Skill (`/design`) — Design Spec

**Date:** 2026-06-08
**Status:** Draft for review (q1–q4 resolved; q2/q3 settled empirically; §10 decisions locked 2026-06-08 — pending user spec review before implementation)
**Topic:** A second, independent presentation mode that **designs slides from scratch as a designer** within the Cloud.ru 2.0 brand system — emitting **native python-pptx vector shapes only** — instead of filling a donor template. Targets the slide classes the donor path handles badly: charts, diagrams, and picture-heavy slides.

---

## 1. Problem

The current `/verstai` skill is **donor-driven**: it picks 1 of 102 layouts from `Cloud.ru_Template_2026.pptx` and fills its slots. This is excellent for text/bullet/title-subtitle slides but degrades sharply when the source slide is a **chart, a process/diagram, or an image composition** — there is no donor slot that matches, so content is force-fit, overflows, or is dropped (see memory: image-only slides dropped, card_grid fragmentation, off-slide bleed).

The donor model also can't *invent* visual structure: it can only re-use a frozen layout. A chart slide needs a real native chart; a 5-node architecture needs real connectors; a KPI trio needs deliberate composition — none of which exist as donor slots.

**Decision (user):** build a **separate skill + separate bot scenario** that draws slides from scratch, acting as a designer constrained by brand *patterns* (not by the template as a donor), and outputs **native, editable vector shapes** (no raster/PNG bake, no SVG).

## 2. Goal & Non-Goals

**Goal:** Given a parsed deck, produce a brand-correct `.pptx` where every slide is **composed from scratch** as native python-pptx shapes (autoshapes, textboxes, native charts, freeforms), driven by an LLM that emits a **Composition DSL on a relative grid** — never EMU, never placeholder indices, never donor IDs.

**Non-Goals:**
- No changes to the `/verstai` graph, donor map, `build_v9`, or any donor renderer. The two modes are fully isolated (see §9).
- No raster bake, no SVG, no `exec`-ing LLM-generated Python. Native shapes only.
- The brandbook is a **pattern source, not an asset source** — its line illustrations are embedded raster and are *re-drawn* as native vectors per the geometric rules in §6, never copied.
- No new infra: reuse the existing Celery task, Redis, worker render. `/design` adds an in-task mode branch only.

## 3. Empirical Findings (this spec is grounded in tests, not guesses)

### q2 — DSL → native_assembler path (PROVEN)
Prototype `tmp/q2_proto.py` built 3 archetype slides (data-chart hero, dark pie+body, dots+KPI trio) through `composition_dsl → native_assembler → primitives`, saved `.pptx`, reopened, and validated: all shapes **in-canvas, 0 off-canvas**, native chart present, reopens cleanly. **Verdict: the DSL→native path is deterministic, structurally valid, and on-brand.** SVG was rejected (violates native-only); LLM-emits-code was rejected (unsafe `exec`, non-deterministic, no validation layer). The DSL gives us a typed, validatable contract the LLM cannot break.

**One finding to fix:** the `dots` background drew **490 individual ovals** on the KPI slide (file bloat). → §6.4: dot/grid patterns must be a single tiled picture-fill or a coarse, capped lattice, **not** one shape per dot.

### q3 — art_director: combined vs split (PROVEN, live Cloud.ru FM, GLM-5.1 thinking-ON)
A/B on the same 8-slide board-report brief (`tmp/q3_artdirector_ab.py`, result `tmp/q3_ab_result.json`):

| Variant | Calls | Tokens | Latency | Result |
|---|---|---|---|---|
| **COMBINED** (tonality+motifs in one prompt) | 1 | **2202** | **95.9s** | mixed / dark_ratio 0.25 / sparkle low / portal cover / flat / outline_corners / **balanced** |
| **SPLIT** (step1 tonality → step2 motifs conditioned on it) | 2 | 4865 | 139.4s | light / 0.0 → sparkle none / portal none / flat / outline_corners / **airy** |

**Verdict: COMBINED wins.** It is **2.2× cheaper** and **1.45× faster**, and produced the *better art direction*: reasoning about tonality and motifs jointly yielded a deliberate dark cover/finale for premium contrast at balanced density. SPLIT's sequential conditioning **starved** the design — step1 locked "light" in isolation, then step2 rationalized away all variety ("airy", everything `none`), which is exactly the **sparse-underfill defect** already tracked in this project. → **art_director is ONE combined step emitting the full locked design-stub.**

### PDF brandbook extraction (vector primitive specs)
Full geometric specs captured in `skill_assets/brand/brandbook_2.0/Приложение_2_Vector_Primitive_Specs.md`. Build-constants that drive §6:
- **Micromodule = 2 px**: every internal spacing/offset divisible by 2. **Outer margins divisible by 10** (10/20/30/40…).
- **Brand Black = `#222222`** (NOT `#0E0E0E` as a prior note said). Green = `#26D07C` (code-consistent).
- **Портал** = N identical **squares**, each offset **(+~24 % right, −~7.5 % up)** of side from the previous, up-right staircase, fill `#222222`, square corners; rotate 90°/180° + mirror only; used as backing plate or image mask.
- **Sparkle** = 4-point star with **concave sides**; **Cloud** = outline, flat bottom, angular bumps, **square caps**. Stroke weights **2/4/6 px** (1 px small-icon exception only). Max 2 colors per illustration.
- **Arrow (flow)** = straight shaft, square cap, optionally on a **45°-rotated green square** backing (fill must differ from line color).
- **All decor: square caps, square joins, right angles, NO rounding** (global Look&feel constant).
- **Type:** SB Sans Display (headings/big numbers) / Text (body) / Interface (infographics). Leading 120 % normal, 100 % dense; **big numbers tracking −4..−7**; **inter-block gap = heading cap-height**.

## 4. Target Data Flow

```
parse_node (REUSED from /verstai — parse_pptx, recursive group walk)
   ↓ ParsedDeck (slides: text, tables, charts-data, images, geometry)
brief_node (REUSED — Kimi vision grounding on slide PNGs)
   ↓
art_director_node            [NEW]  combined: ONE locked design-stub for whole deck
   ↓  (locked_stub carried VERBATIM to every downstream node — DKeken #1)
slide_planner_node           [NEW]  per-slide: pick archetype + assign a tone budget
   ↓
slide_composer_node          [NEW]  per-slide: emit Composition DSL (blocks on 12×10 grid)
   ├─ chart_designer  (sub)   [NEW]  for chart archetypes → ChartBlock spec
   └─ diagram_designer (sub)  [NEW]  for flow/timeline/team → connector+node blocks
   ↓  list[Composition]
typography_node              [NEW]  normalize type scale / leading / tracking to stub
   ↓
brand_critic_v2_node         [NEW]  dual audit+conformance gate → READY / NOT-READY
   ↓  (NOT-READY → bounded re-compose loop, max N; DKeken #5)
native_assemble_node         [NEW]  Composition → native_assembler.build_deck → .pptx
   ↓
render_png + visual_verify   (REUSED — worker-side soffice render + Kimi check)
   ↓
finalize (REUSED)
```

**Key invariants (DKeken methodology, adapted):**
- **#1 Locked stub:** `art_director` output is frozen and passed verbatim to every node; nodes may *read* it, never *mutate* it.
- **#3 Do-not list:** the stub carries an explicit `forbidden` list (no glassmorphism/neon/gradient/shadow/rounding>4px, no >1 green flood, no non-brand color) injected into every composer/critic prompt.
- **#4 Dual critic:** `brand_critic_v2` runs two passes — **audit** (does it match the locked stub & brand canons?) and **conformance** (is the DSL structurally renderable & in-canvas?).
- **#5 Gate:** critic emits a binary `READY`; NOT-READY triggers a bounded re-compose (default max 2) before falling back to the safest archetype.
- **#7 Text is sacred:** composer may re-layout and re-emphasize, never paraphrase source copy.

## 5. Slide Archetypes (≥7, each a composer template + critic checklist)

Each archetype is a parametrized grid recipe the composer fills. The planner assigns one per slide from the brief.

1. **cover** — full-bleed; optional dark portal backing (per stub `portal_usage=cover`); title (Display SemiBold) + subtitle; one sparkle accent. Tone may be dark even when deck is light (q3 showed this reads premium).
2. **data-chart** — title band (rows 1–2) + native chart (≤8 cols) + optional KPI callout sidebar; exactly ONE green accent series, rest pastel ramp. *The archetype the donor path breaks on.*
3. **kpi** — 1–3 big numbers (72pt Display, graphite **not green**, tracking −4..−7) + captions; optional dots background (capped, §6.4).
4. **diagram-flow** — 3–6 nodes (rounded-rect ≤4px) connected by **arrows** (square cap, optional 45° green rhombus backing); left-to-right or top-down; labels inside nodes (text sacred).
5. **comparison** — 2–3 columns of matched rows (e.g. before/after, plan/fact); header plashka per column; one column may carry the green accent.
6. **timeline** — horizontal axis with 4–6 milestones; tick + label + short copy; even micromodule spacing; no per-card overflow (a known donor defect — fixed here by grid-cell clamping).
7. **team** — 2–4 person cards: avatar placeholder block (portal-square mask or gray plate) + name (SemiBold) + role; uniform grid.
8. **section-divider** — minimal: large section title + index, optional outline-corner decor; can be the one dark slide in a light deck (counts against `dark_ratio`).

Fallback archetype (critic NOT-READY exhausted): **title+body** (safest, always renderable).

## 6. Components (isolated, independently testable)

Existing prototype modules under `renderers/designer/` (created & validated in q2):

### 6.1 `composition_dsl.py` — the LLM contract (EXISTS)
Pydantic models on a **12×10 grid**: `Grid(c,r,cs,rs)`, `TitleBlock`, `BodyBlock`, `KpiBlock`, `ChartBlock(+ChartSeries)`, `DecorBlock`, `Background`, `Composition`. `extra="forbid"` everywhere so malformed LLM output fails validation (not silently). **To add for §5:** `NodeBlock` + `ConnectorBlock` (diagram-flow), `CardBlock` (team/comparison), `MilestoneBlock` (timeline). Grid bounds (1..12 / 1..10) already enforce in-canvas placement.

### 6.2 `native_assembler.py` — deterministic DSL → shapes (EXISTS)
`_grid_to_px` maps grid cells → px within a 40px safe margin; `assemble_slide` draws background then dispatches each block to `primitives`; `build_deck` sets the 1280×720 canvas and saves. **To add:** node/connector/card/milestone dispatch + **snap all derived offsets to the 2px micromodule and margins to 10px** (PDF §3).

### 6.3 `primitives.py` — native vector primitives (EXISTS, extend)
Has `background`, `title_block` (green plashka-**underline as element, not letter color** — canonical), `body_block`, `kpi_block` (graphite number), `chart_block` (native `add_chart`, exactly one green series + pastel `NON_ACCENT` ramp), `outline_corner`, `sparkle` (freeform 4-point). **To add:** `portal(slide, n, side, anchor)` (staircase squares, offset +24%/−7.5%, `#222222`), `arrow(slide, p0, p1, rhombus=False)` (square-cap connector, optional 45° green rhombus), `node_box`, `person_card`, `milestone_tick`. **Fix from q2:** replace `_dot_pattern`'s 490 ovals with a **single tiled picture-fill or a coarse capped lattice** (≤ ~60 shapes).

### 6.4 Pattern/background rule (q2 fix)
`dots`/`grid` backgrounds must NOT emit one shape per dot. Implement as either a pre-rendered tile applied as a shape fill, or a capped coarse lattice. Hard cap shapes-per-slide in the critic conformance pass.

### 6.5 LLM roles (NEW entries in `llm/roles.py`)
Reuse existing models; add roles so prompts are per-role:
- `ART_DIRECTOR` → GLM-5.1 **thinking-ON** (q3 used this; deep reasoning, one combined call, ~2200 tok budget → set `max_tokens` ≥ 2500).
- `SLIDE_COMPOSER` → DeepSeek-V4-Pro or GLM-5.1 thinking-OFF (structured JSON emit, low latency).
- `CHART_DESIGNER` / `DIAGRAM_DESIGNER` → GLM-5.1 thinking-OFF (data→spec mapping).
- `BRAND_CRITIC_V2` → GLM-5.1 thinking-ON (the gate; reuse the strong reasoning model).
All prompts **re-engineered per model** (memory: original skill prompts are Claude-tuned).

## 7. The Locked Design-Stub (art_director output)

The single source of truth, frozen after one combined call (q3 schema, validated live):
```json
{
  "tonality": "light|dark|mixed",
  "dark_ratio": 0.0,
  "palette_roles": {"bg": "...", "text": "...", "accent": "#26D07C"},
  "type_scale": {"title_pt": 44, "body_pt": 16, "kpi_pt": 72},
  "motif_mix": {
    "sparkle_density": "none|low|med",
    "portal_usage": "none|dividers|cover",
    "geometry": "flat|isometric|mixed",
    "decor": "none|outline_corners|full",
    "density_target": "airy|balanced|dense"
  },
  "forbidden": ["glassmorphism","neon","gradient","shadow","rounding>4px","green_flood","non_brand_color"],
  "rationale": "1-2 sentences tying choices to positioning/audience"
}
```
Carried verbatim into every composer/critic prompt. `dark_ratio` budgets which slides may be dark; the planner spends it on cover/divider first.

## 8. Brand Critic v2 (gate)

Two passes over each `Composition` (and the deck as a whole):
- **Audit (LLM, GLM-5.1 thinking-ON):** matches locked stub? one green accent only? type scale honored? `forbidden` list respected? motif usage within `motif_mix`? `dark_ratio` not exceeded across deck?
- **Conformance (deterministic, no LLM):** DSL validates? all blocks in-canvas (grid bounds already guarantee, but verify after px conversion)? shapes-per-slide under cap? chart series ≤ limit? text not paraphrased (hash/compare against source)?

Output `READY|NOT-READY` + reasons. NOT-READY → re-compose that slide (max 2), then fall back to **title+body** archetype. Mirrors the existing pipeline's `process_verify/autofix` discipline but for the native path.

## 9. Isolation from `/verstai` (two branches, two chats)

Developed in worktree `Slides_bot_design` on branch `feature/designer-skill`; `/verstai` stays on `main` in `Slides_bot`. Shared-file touchpoints are **additive only** (no edits to existing donor logic):

| Shared file | Additive change |
|---|---|
| `schemas/session.py` | add `Mode.DESIGN = "design"` + `"design"` to the `mode` Literal |
| `bot/app.py` | register `CommandHandler("design", design)` |
| `bot/handlers/` + `bot/i18n/ru.py` | new `/design` handler + RU strings |
| `worker/tasks/pipeline.py` | 1-line branch: `mode=="design"` → designer graph |
| `llm/roles.py` | append new roles (§6.5); existing roles untouched |

New namespaces (no collision): `renderers/designer/`, `graph/designer/` (or designer nodes under a subpackage), `skill_assets/brand/brandbook_2.0/`, designer prompts under `llm/prompts/designer/`. Brand artifacts live only in the design worktree so they don't contaminate the `/verstai` branch.

## 10. Decisions (resolved 2026-06-08)

1. **Graph wiring — DECIDED: standalone `designer_graph`.** Cleanest isolation, zero risk to `/verstai` nodes. `worker/tasks/pipeline.py` branches by mode to pick the designer graph.
2. **Re-compose budget — DECIDED: max 2 retries per slide**, then fall back to the title+body archetype. Accepts the ~1.5–2 min/call latency of the strong model for the quality gain.
3. **Raster-chart source — DECIDED: OCR/estimate the values and draw a native chart** (user override of the "image archetype" lean). **Guardrails (mandatory, since fabricated data in a report is the real risk):**
   - Use the **Kimi vision** role on the grounding PNG to read axis labels, categories, and bar/point values; emit them into a `ChartBlock` with `data_provenance: "estimated"`.
   - `brand_critic_v2` conformance pass requires every estimated chart to carry a small **"оценка по графику"** footnote and flags any chart where values couldn't be read with confidence.
   - On low-confidence / unreadable axes → **degrade to image archetype** (place the original as-is) rather than invent numbers. So OCR is the primary path; image is the safety floor, not the default.
   - Native charts (real chart data in the source) always reuse the exact data — never re-estimate.
4. **`portal` as image mask — DECIDED for v1: simple square plate** (gray/`#222222`) behind avatars/images; freeform clip-mask deferred to a later iteration.

---

### Appendix — Build constants (single source: `_shared.py` + brandbook)
- Canvas 1280×720 px, EMU_PER_PX 9525, safe margin 40px.
- Micromodule 2px (spacing ÷2); outer margins ÷10.
- Black `#222222`, Green `#26D07C`; pastel non-accent ramp BFC7CE/D8DDE1/9AA4AD/E5E8EB.
- Stroke 2/4/6 px, square caps/joins, right angles, no rounding (>4px forbidden).
- Type: SB Sans Display (head/number) / Text (body) / Interface (infographic); leading 120% normal / 100% dense; big-number tracking −4..−7; inter-block gap = heading cap-height.
- Portal step offset (+24% right, −7.5% up) of side, up-right.
