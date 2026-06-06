# Sparse Slides — Content-Volume Telemetry (Phase 2A) — Design Spec

**Date:** 2026-06-06
**Status:** Draft (pending user review) — revised after offline corpus probe
**Topic:** Phase 1 keyed sparse detection on body-slot *occupancy* and flagged nothing. An offline probe over 46 historical assemble plans (deduped) confirms **why and corrects the picture**: on real flat donors the distributor fills every slot (occupancy = 0% useful signal), and genuine underfill manifests as body slots holding *trivially little text* (1–2 words). This spec ships a single **per-slot word-volume** telemetry signal (telemetry-only, no mutation), drops the occupancy signal entirely, and guards against timeline donors that mimic sparseness by design.

Prerequisite reading: `2026-06-06-auto-structuring-sparse-slides-design.md` §8 (Phase 1 findings).

---

## 1. Problem & Corpus Evidence

Phase 1 detected sparseness via `filled / total` body-slot **occupancy** and flagged 0/52 on dl1/dl2/dl3. To learn whether the sparse-flat problem is real, an **uncommitted offline probe** measured content volume across **all 46 persisted `plan.json` dumps** (no LLM, no pipeline run — pure read of assembled plans; body slot = slot name resolving to OOXML `BODY`).

**Deduped findings (44 unique eligible flat-donor slides):**

| Signal | Slides | Share |
|---|---:|---:|
| empty body slot (Phase-1 occupancy) | **0** | **0.0%** |
| ≥1 thin body slot (≤2 words) | 3 | 6.8% |
| whole-slide word_total ≤ 12 | 3 | 6.8% |
| **union (any sparse signal)** | **4** | **9.1%** |

Healthy slides are well-filled: word_total median **47**, p25 33. The thin tail (e.g. donor 34, body 3/3 but `[1,2,2]` = 5 words) sits far below, so the gap is clean.

**Two corrections to the Phase-1 picture:**
1. **Occupancy is dead, and Phase 1 was right.** On real flat donors every body slot is filled (`fill_ratio` histogram = `{1.0: 44}`). Agent 04 sizes the donor to content, Agent 03 packs every slot. An empty body slot never reaches build.
2. **The earlier "27%" was timeline contamination.** Before excluding timeline donors, occupancy looked like a 19.6% signal — but those were all donor 60 (`step1_date/step1_body … step10_body`): a variable-length roadmap where partial fill is *by design*, not sparseness. Excluding timeline donors drops occupancy to 0% and total prevalence to ~9%.

**Conclusion:** the genuine sparse-flat population is **~7–9%**, concentrated on multi-column donors (esp. donor 34, the 3-column feature layout), and detectable **only** by content volume — specifically per-slot word count.

## 2. Goal & Non-Goals

**Goal:** Emit, for every eligible flat-donor slide, a per-slot **word-volume** telemetry record so the thin tail is observable in production and confirmed against the offline numbers before any remedy ships.

**Non-Goals:**
- **No mutation.** Output stays byte-identical (same as Phase 1).
- **No occupancy signal.** The Phase-1 `fill_ratio` / `sparse_candidates` occupancy path is **removed**, not kept — it flags nothing on flat donors and only produced timeline false positives.
- **No remedy.** Repacking is Phase 2B, gated and low-priority (§6).
- **No two-metric design.** Single signal: per-slot word count. (Prior draft proposed chars+words+occupancy; the probe shows words alone is the discriminator.)
- No changes to `build_v9`, `donor-slot-map.yaml`, native paths, or injectors.

## 3. The Signal

Per eligible slide, for each **filled** body slot record its word count; flag the slide for telemetry when it has a thin slot.

- `body_words_per_slot` — `[len(text.split()) for each filled body slot]`.
- `thin_slot_count` — number of filled body slots with `words <= _SPARSE_THIN_WORDS`.
- `body_word_total` — sum across body slots (context for judging the whole-slide extreme tail).

`_SPARSE_THIN_WORDS = 2` — a body slot carrying ≤2 words is "thin" (matches the 3 flagged slides; median healthy slot is far above). Telemetry-only: a slide is *logged* when `thin_slot_count >= 1`; nothing is mutated.

## 4. Where it hooks & Eligibility

Same site and gate as Phase 1 (`distribute_node` tail). Eligibility, with **one addition**:
- `layout_idx != 0` (donor route),
- `category in {text, multicolumn}`,
- not a `_split_part`,
- `body_slots_total >= 3`,
- **NEW: not a timeline donor** — a donor whose slot names include both `*_date` and `step\d+_body` is a variable-length roadmap; partial fill is intentional, so it is exempt (this is what produced the false-positive "underfill" in the probe).

## 5. Components (Phase 2A, isolated + testable)

### 5.1 `donor_map.is_timeline_donor(layout_idx) -> bool` — NEW, pure
Returns True when the donor exposes paired `*_date` + `step\d+_body` slots. Reuses `_load()`; independently unit-testable (donor 60 → True; donor 34/33/29 → False).

### 5.2 Replace `_detect_sparse_slides` body with the volume signal — MODIFIED
Keep the function name and call site; swap the trigger from occupancy to thin-slot volume, add the timeline guard, and update the payload:
```
{num, source_slide, category, layout_idx,
 body_slots_total, body_slots_filled,
 body_words_per_slot:[...], thin_slot_count, body_word_total}
```
The occupancy fields (`fill_ratio`, `real_item_count`) and `_SPARSE_FILL_RATIO` constant are removed. Pure, no I/O, no mutation.

### 5.3 `distribute_node` log rename — 1 line
Emit `node.distribute.sparse_volume` (was `sparse_candidates`) with the new payload. The `node.distribute.done sparse_candidates=N` summary field is renamed `thin_slides=N`. Nothing else changes.

## 6. Phase 2B (remedy) — gated, LOW priority

The corpus says the problem is real but modest (~9%, of which only ~2–4% are egregious like the 5-word slide). Per quality-over-tokens it is worth fixing (a 3-column donor holding 5 words is a visible defect), but scope tightly:
- Trigger on the **egregious tail only** (e.g. whole-slide `body_word_total` below a floor, or ≥2 thin slots), not all 9%.
- Concentrate on the multi-column donors that actually exhibit it (donor 34-like).
- Built in a separate spec/plan once 2A confirms the offline numbers hold in live production.

## 7. Risks & Mitigations
- **Tiny population → remedy may not pay off.** Accepted; 2A is cheap telemetry and 2B is explicitly gated on confirming the tail in prod.
- **Timeline-guard misses a variant.** The `*_date` + `step\d+_body` pattern matches the known roadmap donors; a unit test pins donor 60 → exempt, 34/33/29 → eligible. If a new roadmap donor appears without that naming it would be a false positive again — caught by eyeballing flagged PNGs.
- **Thin threshold off.** ≤2 words is read from the flagged set; recalibrate from live `sparse_volume` if the tail shifts.

## 8. Success Criteria (Phase 2A)
- `node.distribute.sparse_volume` emits per thin flat-donor slide with no change to produced decks (output diff = ∅), verified by the same no-mutation property test as Phase 1.
- Unit tests: `is_timeline_donor` (60→True, 34/33/29→False); the rewritten detector over synthetic fixtures (thin 3-col flagged; dense 3-col not; timeline donor exempt; split/native/<3-slot exempt; full-occupancy-but-thin flagged — the case occupancy missed).
- All existing tests stay green; Phase-1 occupancy tests updated to the volume signal.
- Findings appended once live `sparse_volume` confirms (or refutes) the ~9% offline figure, ending in an explicit **build / do-not-build** verdict on Phase 2B.

## 9. Resolved (was Open Questions)
1. **Corpus source** — resolved for free via the offline `plan.json` probe (44 unique eligible slides); no organic accumulation or synthetic seeding needed.
2. **Words vs chars** — words. Per-slot word count is the discriminator; chars/occupancy dropped.
3. **Keep Phase-1 occupancy line?** — removed. It flags nothing on flat donors; its only hits were timeline false positives.
