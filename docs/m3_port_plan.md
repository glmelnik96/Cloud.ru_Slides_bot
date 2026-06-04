# M3 Port Plan — Cloud.ru Slides Skill → Slides_bot

_Source: Explore subagent analysis of `cloud-ru-slides-skill-v2.4.1` (2026-06-04)._

## 1. Pipeline data flow (v0.9 batch)

10 sequential agents/stages:

| # | Stage | Kind | Role |
|---|---|---|---|
| 01 | Brief Reader | LLM + vision | Extract topic, audience, per-slide intents from .pptx |
| 02 | Slide Classifier | LLM / rules | Map intents to 12 categories + 6 native render types; **split overloaded slides** |
| 03 | Content Distributor | LLM / semantic | Distribute text to placeholders; priority heuristics |
| 04 | Layout Designer | LLM / lookup | Pick `layout_idx` 0–102 from donor catalog; anti-monotony |
| 05 | Icon Picker | LLM / matching | Extract keywords → SVG icons |
| 06 | Infographic Maker | LLM / geometry | Shape coordinates in EMU |
| 07 | Copy Editor | LLM / rules | Russian typography (nbsp, dashes, quotes) |
| 08 | Brand Guardian | Python | Validate colors/fonts/sizes; score 0–100 |
| 09 | Process Verifier | Python | Orchestrate verdicts, gate |
| 10 | Visual Verifier | LLM + vision | 5-dim rubric (philosophy/hierarchy/detail/function/innovation), Ghost Deck Test |

**Output**: branded `.pptx` with `brand_score ≥ 70` and `visual_score_avg ≥ 4/5`.

## 2. Schema contracts → `schemas/slides.py`

9 Pydantic models, one per inter-agent JSON shape:

| Schema | Producer | Key fields | Consumer |
|---|---|---|---|
| `Brief` | 01 | `topic`, `audience`, `tone`, `slides[]{intent, key_phrase}` | 02, 03 |
| `SlideClassification` | 02 | `category` (12-enum), `slide_type` (kpi_native\|chart_pptx_native\|table_native\|flow_diagram_native\|image_native\|donor), `native_config` | 03, 04, 06 |
| `LayoutPlan` | 04 | `layout_idx` (0–101), `slot_styles_override` | 03, 09 |
| `ContentAssignment` | 03 | `placeholder_assignments[]`, `dropped_content[]`, `warnings[]` | 05, 06, 07 |
| `CopyEditedAssignment` | 07 | cleaned `placeholder_assignments`, `edits_count` | build |
| `BrandReport` | 08 | `verdict` (OK\|WARN\|FAIL), `score`, `violations[]` | 09 |
| `VerifierVerdict` | 09 | `verdict`, `score_avg`, `checklist_results`, `blockers[]` | user |
| `VisualVerdict` | 10 | `llm_verdict`, per-slide `hard_checks` + 5-dim scores | 09, user |
| `Plan` | orchestrator | `slides[]{clone_from_slide\|slide_type, slots, overrides}` | `build_v9.py` |

## 3. Brand assets to vendor → `skill_assets/`

**Critical at runtime:**

- `brand/palette.json`
- `brand/donor-slot-map.yaml` — **single source of truth** for `layout_idx`, `safe_max_chars`, canonical styles
- `brand/template-layouts-dump.json` — 102 layouts with placeholder coords
- `brand/template-canonical-rules.md`, `brand-rules.md` — agent context
- `brand/design-tokens.yaml` — forbidden elements
- `brand/template-version.json` — slide indices for kpi/flow renderers
- `dictionaries/short-words-ru.txt`, `whitelist.txt`
- `Cloud.ru_Template_2026.pptx` — master template (102 layouts, verified)

## 4. Scripts triage

**Port as-is:** `kill_widows.py`, `parse_docx.py`, `parse_md.py`, `extract_images.py`, `effects_util.py`, `enforce_canonical.py`, `visual_validator.py`, `chart_native_pptx.py`, `template_path.py`.

**Port w/ light changes** (hardcode `skill_assets/` paths, accept bytes):
- `parse_pptx.py` — read bytes (Telegram upload)
- `build_v9.py` (**CRITICAL**) — return `.pptx` bytes
- `validate_plan.py` — point to `donor-slot-map.yaml`
- `brand_guardian.py` — point to `palette.json`
- `kpi_renderer.py`, `flow_renderer.py`, `table_renderer.py`

**Skip:** `build_v2-v8`, `layout_designer`, `sync_template`, `chart_engine` (obsolete).

## 5. LLM prompt rewriting (WS-E)

| Agent | Model | Difficulty | Notes |
|---|---|---|---|
| 01 Brief | Kimi-K2.6 (vision) | M | Strip Claude voice, explicit JSON, vision optional |
| 02 Classifier | DeepSeek-V4-Pro | L | Embed 12-category table + split rule deterministically |
| 03 Distributor | GLM-5.1 | M | Explicit priority (numbers > actions > context) |
| 04 Designer | DeepSeek-V4-Pro | L | Lookup table in prompt; anti-monotony |
| 05 Icons | GLM-5.1 | L–M | Keyword match, strict fallback `TODO` |
| 06 Infographic | GLM-5.1 | M–H | Pixel coords explicit, geometry rules |
| 07 Copy Editor | GLM-5.1 | L | Rule-based, can be made deterministic |
| 10 Visual Verifier | Kimi-K2.6 (vision) | H | Hard checks gate, forbid “PERFECT” bias |

**Common Claude-isms to strip:** "You (Claude)", artifact refs, implicit JSON parsing, subjective language.

## 6. v0.9 batch vs v0.17 per-slide loop

**Batch wins** for M3 because:
1. **Agent 02 split**: 4+ KPI / 6+ blocks → splits a slide into 2–3 → renumbering breaks per-slide loop.
2. **Agent 04 anti-monotony** is a global rule — needs the whole deck in view.
3. **Agent 10 Ghost Deck Test** extracts titles → narrative coherence; per-slide can’t see neighbours.
4. `build_v9.py` expects a complete `Plan` — incremental rebuild = major refactor.

**Decision: v0.9 batch for M3.** Per-slide loop deferred to v0.18+ if needed.

## 7. Critical gotchas

1. `donor-slot-map.yaml` is the **only** source of truth for `layout_idx` — never hardcode.
2. Execution order: `build → brand_guardian → enforce_canonical → render PNG → visual_verifier`.
3. Flow safe-area: `x ∈ [35, 1245]`, `y ∈ [140, 660]` (pixels) — overflow = visual overlap.
4. Native renders (KPI/table/chart) draw on **blank** canvas, not donor placeholders.
5. Text color: `#222222` graphite (or white on dark). Green text = brand fail.
6. Agent 02 split rules are deterministic — not LLM judgment.
7. PNG rendering ≈ 1 s/slide via LibreOffice headless (already in worker image).
8. Telegram file cap: 50 MB.

## 8. Acceptance criteria (full M3)

**Functional:** user uploads `.pptx` → bot returns branded `.pptx`; text preserved; opens cleanly.
**Quality:** `brand_score ≥ 70`; `visual_score_avg ≥ 4.0`; no slide `< 3.0`; anti-monotony respected.
**Technical:** all 3 models wired correctly; Pydantic-validated schemas; 1-retry on validation fail; assets vendored.

## 9. Cost ballpark (10-slide deck)

- ~10–15K tokens total across all stages
- Mixed-model cost: ~$0.21–0.30 / deck
- Wall time: 2–3 min
