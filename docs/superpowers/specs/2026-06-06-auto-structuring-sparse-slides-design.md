# Auto-Structuring Sparse Slides — Design Spec

**Date:** 2026-06-06
**Status:** Draft (pending user review)
**Topic:** Catch slides that landed in a flat `text`/`multicolumn` donor but fill only a fraction of its body slots ("lonely header over empty brand decoration"), and repack their *real* content into a right-sized native layout or smaller donor — without inventing content.

---

## 1. Problem

A source slide carrying only 1–2 short points sometimes gets classified into a 4–6-slot `text`/`multicolumn` donor. Build fills 1–2 slots and leaves the rest empty, so the rendered slide shows a lonely header over large empty brand decoration — visually underfilled, low information density.

This is the **sparse / underfilled** case (interpretation A, confirmed with user). It is *not* about promoting dense flat-bullet "text walls" to richer layouts — that is explicitly out of scope.

**Why existing logic doesn't catch it.** The pipeline already structures content in several places, but each targets *overflow*, not *underfill*:
- Agent 02 splits columns with `body >80 words` (too much, not too little).
- Agent 03 splits "стена текста" `>200 chars` (too much).
- Agent 04 density thresholds prefer a native preset when content *overflows* a donor.
- `_inject_parsed_tables` / `_inject_visual_slides` recover tables/visuals, not sparse text.

None of them fire when a slide is *under* the donor's capacity. So underfilled slides slip through to build as-is.

## 2. Goal & Non-Goals

**Goal:** A flat `text`/`multicolumn` slide that fills ≤ half of its donor's body slots is detected and (Phase 2) repacked into a layout sized to its real content — native preset when the content's shape fits one, else a smaller-slot donor. Zero invented content.

**Non-Goals:**
- No promotion of well-filled / dense slides ("text wall") to richer layouts — out of scope.
- No rewriting, summarising, or expanding copy. Only the *container* changes; text is moved verbatim.
- No changes to `build_v9` core, `donor-slot-map.yaml`, the table/kpi/chart/visual native paths, or the existing injectors.
- No new renderers — reuse `flow_renderer` presets (`hero_statement`/`card_grid`/`numbered_*`) and existing donors.

## 3. Two-Phase Delivery (telemetry-first)

Confirmed with user: **C → A**. Ship the detector first with the remedy *disabled*, run on real decks, calibrate the threshold, *then* enable the remedy. This mirrors the Feature 1 loop (run on Downloads → read log → fix).

### Phase 1 — Detector + Telemetry (this spec's buildable unit)
- Deterministic detector flags sparse-candidate slides and logs full diagnostics.
- **No mutation** of the classification/content. Pipeline output is byte-identical to today.
- Run on dl1/dl2/dl3, inspect `node.distribute.sparse_candidates`, confirm the detector catches the real underfilled slides and *not* healthy ones.

### Phase 2 — Remedy (gated; built only after Phase 1 calibration)
- Hybrid (confirmed mechanism B): deterministic detection + deterministic fallback; the native-preset *choice* may use the LLM signal where it survives, with a deterministic floor.
- Remedy C: native preset when content shape fits; else swap to a smaller-slot donor.
- Built in a **follow-up spec/plan** once Phase 1 numbers justify the exact thresholds and remedy routing. Not implemented in this iteration.

## 4. Detection (Phase 1)

### 4.1 Where it hooks
A new deterministic helper runs at the **end of `distribute_node`** (`graph/nodes/agents.py`). That is the earliest point where both signals exist:
- the chosen donor (`layouts[].layout_idx`) → body-slot capacity, and
- the placed content (`content[].placeholder_assignments`) → how many slots got real text.

Detector reads `arts["classification"]`, `arts["layouts"]`, `arts["content"]`. It is positioned as a **backstop** (interpretation A confirmed): it only inspects slides that already landed in a flat donor, never second-guesses good decisions.

### 4.2 Body-slot capacity
Per slide donor, count *body* slots from the slot map (slot semantic name contains `body` — `body`, `col1_body`, `col2_body`, `body_left`, …; via `donor_map`). Title/footer/eyebrow/decorative slots do not count toward capacity.

`body_slots_total` = number of body slots the donor exposes.
`body_slots_filled` = number of those slots whose mapped `PlaceholderAssignment.content` is non-empty after trimming.

### 4.3 Eligibility (what the detector even looks at)
A slide is a **candidate for inspection** only if ALL hold:
- `layout_idx != 0` (donor route — natives are sized by their own renderer).
- `category in {text, multicolumn}` (the flat-donor case). `title`/`divider`/`image`/`logo`/`pattern_bg`/`team`/`timeline`/`callout` are exempt — they are intentionally sparse or already specialised.
- not a `_split_part` (split halves are expected to be light).
- `body_slots_total >= 3` (a 1–2-slot donor cannot be "underfilled").

### 4.4 Sparse trigger (starting threshold A — conservative)
A candidate is flagged **sparse** if either:
- `body_slots_filled / body_slots_total <= 0.50`, OR
- `body_slots_total >= 4` and `body_slots_filled <= 2`.

Borderline cases (e.g. 3 of 4 filled, or dense text in 2 of 3) are deliberately **not** flagged. The threshold is a Phase-1 starting point; it will be re-tuned from the telemetry before any remedy ships.

### 4.5 Telemetry output
On detection, emit one structured log line summarising the deck, plus per-slide diagnostics, e.g.:

```
node.distribute.sparse_candidates  count=N  slides=[
  {num, source_slide, category, layout_idx,
   body_slots_total, body_slots_filled, fill_ratio,
   real_item_count, content_chars:[...]},
  ...]
```

`real_item_count` = number of non-empty body assignments (the would-be element count a remedy must rehome). `content_chars` lets us judge by eye whether each candidate is genuinely thin vs. a few long paragraphs (which a remedy should treat differently). No state mutation; this is pure observation.

## 5. Components (Phase 1, isolated + testable)

### 5.1 `donor_map.body_slot_count(layout_idx) -> int` — NEW, pure
Returns the number of body-type slots a donor exposes (reuses the existing `body`-substring slot classification at `donor_map.py:55`). Independently unit-testable against the real slot map.

### 5.2 `_detect_sparse_slides(classification, layouts, content) -> list[dict]` — NEW, pure
Implements §4.2–§4.4. Takes the three artefact dumps, returns the diagnostics list (empty if none). No I/O, no mutation — trivially unit-testable on synthetic dicts. The caller in `distribute_node` logs the result.

### 5.3 `distribute_node` wiring — 1 call + 1 conditional log
After `arts["content"] = …`, call the detector and, if non-empty, emit `node.distribute.sparse_candidates`. Nothing else changes.

## 6. Risks & Mitigations
- **False positives (flagging healthy slides).** Mitigated by the conservative §4.4 threshold + telemetry-only Phase 1 — we *look* before we *touch*. Calibration on dl1/dl2/dl3 confirms before any mutation ships.
- **Capacity miscount** (donor slot map drift). `body_slot_count` reuses the same slot classifier the distributor already trusts; a unit test pins expected counts for a few known donors.
- **Phase 2 over-reach.** Remedy is a separate gated spec; this spec ships no mutation, so the blast radius now is zero.

## 7. Success Criteria (Phase 1)
- Detector runs in every live pipeline with no change to produced decks (output diff = ∅).
- On dl1/dl2/dl3, `node.distribute.sparse_candidates` enumerates the genuinely underfilled slides and excludes the healthy/dense ones (verified by eye against the rendered PNGs).
- Unit tests: `body_slot_count` against real donors; `_detect_sparse_slides` over synthetic eligible/exempt/sparse/dense fixtures (incl. exemption of natives, splits, image/divider categories, and the 1–2-slot-donor guard).
- All existing tests stay green.
