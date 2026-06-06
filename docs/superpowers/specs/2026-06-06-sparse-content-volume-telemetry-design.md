# Sparse Slides — Content-Volume Telemetry (Phase 2A) — Design Spec

**Date:** 2026-06-06
**Status:** Draft (pending user review)
**Topic:** Phase 1 proved that *slot occupancy* is the wrong signal for "lonely header over empty brand decoration" — the distributor fills every body slot it is given, so `filled == total` is the norm. This spec pivots the metric to **content volume** and stays telemetry-only: measure how much real text actually lands in each eligible donor across a wider corpus, so we can decide — from data — whether a sparse remedy (Phase 2B) is warranted at all, and at what floor.

Prerequisite reading: `2026-06-06-auto-structuring-sparse-slides-design.md` §8 (Phase 1 findings).

---

## 1. Problem (carried over from Phase 1 §8)

Phase 1 shipped a deterministic detector keyed on body-slot **occupancy** (`filled / total`). Run live on dl1/dl2/dl3 (52 slides) it flagged **0** slides: only 2 were even eligible, and both were fully packed (ratio 1.0).

Two structural reasons, confirmed in code:
1. **Eligible slides are rare.** After Agent 02/04 + the visual injectors, almost every slide becomes a native (kpi/chart/table/flow/image), a title/divider, or a 1–2-slot donor. Flat `text`/`multicolumn` slides landing in a 3+-body-slot donor are the exception (2/52).
2. **The distributor fills every slot it is given.** Agent 04 sizes the donor to the content *before* distribution; Agent 03 then packs all body slots. So an empty body slot essentially never reaches build. Underfill, if it exists, manifests as slots holding *trivially little text* (1–2 words), not as empty slots.

We therefore do not yet know whether genuine sparse-flat slides occur often enough — or thin enough — to justify a mutation path. We need the **content-volume distribution** before designing any remedy.

## 2. Goal & Non-Goals

**Goal:** Emit, for **every eligible** slide (not just flagged ones), a content-volume telemetry record so we can plot the char-per-body-slot distribution across a wider deck set, then decide whether Phase 2B (remedy) is warranted and pick a data-driven floor.

**Non-Goals:**
- **No mutation.** Like Phase 1, pipeline output stays byte-identical. This is pure observation.
- **No remedy.** Repacking into a smaller donor / native preset is Phase 2B, gated on these numbers.
- **No new threshold enforcement.** We log volume; we do not yet *flag* on it. (We may keep emitting the Phase-1 occupancy `sparse_candidates` line unchanged for continuity, but it is not the decision signal.)
- No changes to `build_v9`, `donor-slot-map.yaml`, the native paths, or the injectors.

## 3. The Metric Pivot

**Phase 1 (retired as a decision signal):** `fill_ratio = body_slots_filled / body_slots_total`.

**Phase 2A (new observation signal):** per eligible slide, measure real text volume in body slots:
- `body_char_total` — sum of trimmed chars across all body-slot assignments.
- `body_char_per_slot` — `[len(text) for each filled body slot]` (already collected as `content_chars` in the Phase-1 payload, but only emitted *when flagged*; here it is emitted for **every eligible slide**).
- `body_word_total` — sum of whitespace-split word counts across body slots (words discriminate "1–2 words per slot" underfill better than chars for short labels).
- `thin_slot_count` — number of filled body slots whose word count `<= _THIN_SLOT_WORDS` (starting probe value, see §5). Observation only — not a flag.

This mirrors exactly the widening the throwaway `sparse_eligible` probe did for occupancy in Phase 1, but for volume and **committed** this time (so the corpus can be gathered over normal live runs, not a one-off patch).

## 4. Where it hooks (unchanged from Phase 1)

Same site: end of `distribute_node`, reusing the same eligibility gate as `_detect_sparse_slides` (§4.3 of Phase 1):
- `layout_idx != 0` (donor route),
- `category in {text, multicolumn}`,
- not a `_split_part`,
- `body_slots_total >= 3`.

The volume probe inspects the *same* eligible set; it simply records volume for all of them instead of applying the occupancy trigger.

## 5. Components (Phase 2A, isolated + testable)

### 5.1 `_eligible_body_volume(classification, layouts, content) -> list[dict]` — NEW, pure
Refactors the eligibility loop out of `_detect_sparse_slides` (§3 above is the gate; the two helpers should share it rather than duplicate it) and returns, for **every eligible slide**, a volume record:
```
{num, source_slide, category, layout_idx,
 body_slots_total, body_slots_filled,
 body_char_total, body_char_per_slot:[...],
 body_word_total, thin_slot_count}
```
No I/O, no mutation. Unit-testable on synthetic dicts.

**Shared eligibility:** extract the gate (split/category/layout/min-slots checks) into one private predicate used by both `_detect_sparse_slides` and `_eligible_body_volume`, so the two telemetry views can never drift on what "eligible" means.

### 5.2 Probe constant
- `_THIN_SLOT_WORDS = 2` — a body slot with ≤2 words is "thin". **Starting probe value only**, used solely to populate `thin_slot_count` for inspection; nothing is flagged on it. The real floor is set from the gathered distribution before any Phase-2B flag exists.

### 5.3 `distribute_node` wiring — 1 call + 1 log
After the existing `sparse_candidates` log, call `_eligible_body_volume` and, if non-empty, emit:
```
node.distribute.sparse_volume  count=N  slides=[ {volume records...} ]
```
Nothing else changes. The Phase-1 `sparse_candidates` line stays for continuity.

## 6. Corpus & Calibration Plan

1. Ship 2A telemetry-only.
2. Run across a **wider deck set** than dl1/dl2/dl3 — gather `sparse_volume` over the next N real/seeded live runs (target: enough eligible slides to see a distribution, not 2).
3. Plot `body_word_total` and `body_char_per_slot` for eligible slides; eyeball the rendered PNGs of the thin tail against the input.
4. **Decision gate:** if eligible slides remain rare *and* none are genuinely thin → **close the feature; do not build Phase 2B.** The §8 finding explicitly warns the problem may be too small to warrant a mutation path. Only if a real thin population emerges do we proceed to Phase 2B with a floor read off the data.

## 7. Risks & Mitigations
- **Still measuring a rare population.** Accepted and intended — the whole point of 2A is to quantify scale before building. The decision gate (§6) can legitimately end with "no remedy."
- **Eligibility drift between the two telemetry helpers.** Mitigated by §5.1 shared predicate + a unit test asserting both helpers agree on the eligible set for a fixture.
- **Words vs chars ambiguity.** We log both; calibration picks the better discriminator empirically rather than guessing now.

## 8. Success Criteria (Phase 2A)
- `node.distribute.sparse_volume` emits for every eligible slide with no change to produced decks (output diff = ∅), verified by the same no-mutation property test as Phase 1.
- Unit tests: `_eligible_body_volume` over synthetic fixtures (eligible thin / eligible dense / exempt category / split / native / <3-slot guard); shared-eligibility test asserting parity with `_detect_sparse_slides`'s gate.
- All existing tests stay green.
- A short findings section (like §8 of the Phase-1 spec) appended once the corpus is gathered, ending in an explicit **build / do-not-build** verdict on Phase 2B.

## 9. Open Questions (for user review)
1. **Corpus source.** Phase 1 used dl1/dl2/dl3. For a volume distribution we need more eligible slides than 52 total decks produced (2). Do we (a) wait and accumulate over organic live runs, or (b) seed a batch of deliberately sparse flat decks to force the eligible population up? (b) gets data faster but is synthetic.
2. **Words vs chars as the headline metric** — happy to log both and decide at calibration, or do you have a prior preference?
3. **Keep or retire the Phase-1 `sparse_candidates` occupancy line?** It flags nothing in practice; keeping it is harmless continuity, retiring it reduces log noise.
