# Designer Visual Redesign — Design Spec

**Status:** approved (brainstorming, 2026-06-08)
**Branch:** `feature/designer-skill` (worktree `Slides_bot_design`)
**Supersedes operationally:** the "all defects solved" verdict of commit b57378e — user reviewed real rendered output and found the result **visually unsatisfactory** vs the Cloud.ru reference template.

## Problem

`/design` output "solves the task" but looks like **naked python-pptx**, not the branded Cloud.ru template. The gap is architectural, not bug-level. User mandate (verbatim):

> Результат неудовлетворительный, необходимо комплексное переосмысление… реши значительное визуальное расхождение с референсами. Почини весь процесс создания. Каждое изменение валидировать **не кодом, а визуально**, прогоняя каждый слайд. Скилл должен действовать **как дизайнер**, не на донорах.

## Root causes (user-confirmed)

1. **No branded visual vocabulary in use** — renderer draws generic rectangles/text. Primitives exist (`primitives.py` has portal, zebra table, 5-color charts, milestones) but a few signature brand elements are missing or unused: green divider-line above each point, colored table headers, display cover title, true green-fill cover.
2. **LLM composes the 12×10 grid blind** — no feedback from the actual render → staircases, overlaps, voids. Deterministic reflow patches the symptom, not the cause.
3. **No archetypes-as-templates** — `archetype_for()` returns a *string hint*; the composer guesses the whole layout. Reference = ~12 fixed, branded layouts.
4. **No visual QA in the loop** — `brand_critic_v2` reads JSON DSL, never the rendered picture; can't see overlaps/voids/brand drift.

## Solution — Strategy C (hybrid) + full vision integration

Shift from "blind grid raffle" to **"designer with eyes"**:

```
parse → brief → classify(+VISION input) → art_director →
   compose(archetype SKELETON + VISION reference) → assemble →
   ┌─ render→PNG → vision-QA critic (≤2 passes) ─┐
   └──────────── re-assemble ←───────────────────┘
→ deck-VISION review → DECK
```

### 1. Brand vocabulary refinements (primitives.py)
Add/upgrade the signature elements that read as "Cloud.ru":
- `divider_line()` — green keyline above a bold sub-head + text item (core "N points" look).
- `table_block()` colored header row (green + 2nd accent) instead of transparent.
- `display_title()` — oversized cover heading.
- `cover_green` composition — full green fill + portal staircase + dot grid.

### 2. Archetype skeletons (new `renderers/designer/layouts.py`)
~12 parameterized layout functions with fixed zones + brand dressing. The composer *fills a skeleton with content* instead of inventing coordinates. Catalog (matches reference distribution):
- Covers/dividers (4): `cover_green`, `cover_dark`, `cover_photo`, `section_divider`
- Content (5): `points_3`, `points_4`, `points_6`, `points_8`, `bullet_list`
- Special (3): `table_zebra`, `chart_columns`, `roadmap_timeline`

### 3. Four vision integration points (model: Kimi-K2.6, only multimodal)
1. **Input vision** (classify): source-slide PNG → understand intent → archetype choice.
2. **Reference few-shot** (compose): brand exemplar PNG of the chosen archetype → composer targets the exemplar. Exemplars pre-rendered from `Cloud.ru_Template_2026.pptx`.
3. **Output QA loop** (assemble): render→PNG → `PIXEL_JUDGE` (Kimi) catches overlap/void/brand-drift → fixes → re-assemble, ≤2 passes.
4. **Deck review** (final): one `VISUAL_VERIFIER` pass over the whole deck for rhythm/dupes/cover/dividers/color balance.

### Models & cost
~4–5N vision/LLM calls per N-slide deck (vs ~2N now). Acceptable under "quality over tokens". Real paid Cloud.ru calls authorized for validation.

## Validation (the core mandate)
**Every change validated VISUALLY, by rendering each slide — never "unit tests passed = done".** Bottom-up so there's always a render: primitives → one archetype end-to-end → vision steps one at a time → all 5 test decks e2e, slide-by-slide visual acceptance. Acceptance criterion = the picture matches the brand reference (judged by me + vision critic).

## Scope guard
`/design` designs vector diagrams/charts/tables/dashboards only — NO raster images, NO image generation. `/verstai` (donor pipeline) is untouched.
