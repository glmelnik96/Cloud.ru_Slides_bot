# HTML-render slide pipeline — design spec

Date: 2026-06-09
Status: approved (build phase, spike-first)

## Problem

Both existing pipelines produce visually weak decks vs the Cloud.ru reference template:
- `/verstai` (donor): clones template slides + swaps text; LLM never sees the render; aggressive autofit/clip hacks.
- `/design` (native vector): composes onto a 12×10 grid DSL the LLM has no priors for; Pillow↔LibreOffice metric mismatch; bounded grid expressiveness.

Root cause: the LLM authors through a narrow custom abstraction. LLMs design far better in **HTML/CSS** (billions of training examples) and a browser-screenshot feedback loop is far more effective than editing grid coordinates.

The Cloud.ru aesthetic is minimalist-precise (flat green #26D07C, SB Sans Display, green hairline rules, dot-grid/bracket motifs, whitespace) — fully reproducible in HTML/CSS.

## Decision

**Path B (hybrid).** Reuse the medium-agnostic front-end; replace the rendering back-end with HTML authored by the LLM, rendered in headless Chromium, then packed as full-bleed images into a .pptx. Output is non-editable (accepted by user); source HTML + speaker notes preserved.

Hybrid composition:
- **Template mode** — ~12 HTML templates pixel-replicating the brand exemplars; LLM picks one + fills a content dict.
- **Freeform mode** — for novel slides, LLM writes HTML using only the shared `brand.css`; policed by the vision-QA loop.

## Constraints / isolation

- New modules only: `graph/html/`, `renderers/html/`. **No edits** to `graph/designer/`, `renderers/designer/`, donor pipeline, or existing bot commands.
- Reuse read-only: `parse/brief/classify/art_director` nodes, `llm/client.py`, `llm/roles.py`, planner archetype mapping, Celery queue, session/progress.
- New bot trigger `/render`; `/verstai` and `/design` stay intact for A/B.
- Spike (`probes/html_spike/`) validates before full build; Playwright dev-local, not added to the worker image until greenlit.

## Architecture

```
parse → brief_reader → slide_classifier → art_director (DesignStub)   [REUSED]
  → [per slide] html_compose(LLM) → chromium_render(PNG)
       → vision_qa(pixel_judge vs exemplar) ──repair→ edit CSS/HTML, re-render
  → pptx_pack (PNG full-bleed per 16:9 slide; text→notes)
  → finalize
```

### Components
1. `renderers/html/brand.css` — `@font-face` (docker/fonts SB Sans), CSS vars from design-tokens.yaml + palette.json, 1280×720 canvas @2×, motif classes (dot-grid, bracket ЛЛЛ, portal). Forbidden effects simply not provided.
2. `renderers/html/templates/` — cover_green, cover_dark, section_divider, bullet_list, points_3/4/6/8, table_zebra, chart_columns, roadmap_timeline, kpi, comparison, team.
3. `renderers/html/render.py` — Playwright Chromium → PNG (viewport=canvas, deviceScaleFactor=2).
4. `renderers/html/pptx_pack.py` — PNG full-bleed → 13.333"×7.5" slide; slide text → notes.
5. `graph/html/{graph,nodes,compose}.py` — new nodes; reuse front-end nodes.
6. `llm/prompts/html/` — composer + repair prompts; reuse pixel_judge/brand_critic patterns.

### Charts
Rendered in-browser (ECharts/Chart.js) themed to brand palette — upgrade over python-pptx charts. (Deferred to after template-mode text slides validated.)

## Validation (spike-first, real decks)

Test inputs = source `.pptx` already used for `/verstai` + `/design`: `Downloads/презы_на_тест/` and `tmp/live_inputs/`.

- **Check 0** — hand-built brand.css + 3 templates rendered via Playwright, eyeballed vs `skill_assets/brand/references/exemplars/*.png`. Retires fidelity-ceiling risk.
- **Check 1** — LLM authors HTML from real slide content; compare vs `/design` output for same slide.
- **Check 2** — vision-QA loop edits CSS and improves a defective slide.
- **E2E** — full deck through the new pipeline; visual review.

Gate: Check 0 ≈ indistinguishable from exemplar → proceed; Check 1 clearly beats `/design` → greenlight full build.

## Success criteria

Rendered slides visually match the reference exemplars (fonts, flat green, hairline rules, motifs, spacing); deck for a real test doc is clearly closer to reference quality than `/verstai` and `/design`; existing pipelines unaffected.
