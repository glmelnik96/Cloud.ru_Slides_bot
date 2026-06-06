# Auto-Structuring Sparse Slides (Phase 1: Detector + Telemetry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic, telemetry-only detector that flags `text`/`multicolumn` slides which fill ≤ half of their donor's body slots ("lonely header over empty brand decoration"), logging diagnostics without mutating pipeline output.

**Architecture:** A pure helper `_detect_sparse_slides()` runs at the end of `distribute_node` (`graph/nodes/agents.py`) — the earliest node where both the chosen donor (body-slot capacity) and the placed content (filled body slots) are known. It reads the `classification`/`layouts`/`content` artefact dumps, applies a conservative sparseness rule, and emits one structured log line. It mutates nothing; the remedy is a separate, later-gated Phase 2 spec.

**Tech Stack:** Python 3.10, LangGraph nodes, `structlog`, `pytest`. Donor capacity comes from `graph/donor_map.py` (reads `skill_assets/brand/donor-slot-map.yaml`). Tests run on HOST via `python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-06-auto-structuring-sparse-slides-design.md` (Phase 1 only).

---

## File Structure

- **Modify** `graph/donor_map.py` — add two pure capacity helpers: `body_ph_indices(layout_idx)` (set of placeholder indices mapping to body slots) and `body_slot_count(layout_idx)` (its length). Add both to `__all__`.
- **Modify** `graph/nodes/agents.py` — add the module-level pure helper `_detect_sparse_slides(...)`; call it at the end of `distribute_node` and emit `node.distribute.sparse_candidates` when non-empty.
- **Create** `tests/unit/test_body_slot_count.py` — pins body-slot counts for known real donors.
- **Create** `tests/unit/test_sparse_detector.py` — exercises `_detect_sparse_slides` over synthetic eligible / exempt / sparse / dense fixtures.

Known real donor body-slot counts (verified against the live slot map, used as test anchors):
- donor **21** (content_text) → **1** body slot (`body`)
- donor **28** (content_2col) → **2** (`col1_body`, `col2_body`)
- donor **34** (content_3col) → **3** (`body1`, `body2`, `body3`)
- donor **29** (content_4block) → **4** (`body1_top_l`, `body2_top_r`, `body3_bot_l`, `body4_bot_r`)

---

## Task 1: Donor body-slot capacity helpers

**Files:**
- Modify: `graph/donor_map.py` (add functions near `slot_name_by_ph_idx` at line ~268; extend `__all__` at line ~287)
- Test: `tests/unit/test_body_slot_count.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_body_slot_count.py`:

```python
"""Phase-1 auto-structuring: donor body-slot capacity helpers.

Anchors against the live donor-slot-map.yaml so the detector's capacity
counting can't silently drift if the slot map changes shape.
"""
from __future__ import annotations

from graph.donor_map import body_ph_indices, body_slot_count


def test_body_slot_count_known_donors() -> None:
    # content_text / 2col / 3col / 4block donors — see plan File Structure table.
    assert body_slot_count(21) == 1
    assert body_slot_count(28) == 2
    assert body_slot_count(34) == 3
    assert body_slot_count(29) == 4


def test_body_slot_count_native_and_unknown_is_zero() -> None:
    assert body_slot_count(0) == 0          # native render — no donor
    assert body_slot_count(999_999) == 0    # not in the slot map


def test_body_ph_indices_match_count() -> None:
    idxs = body_ph_indices(34)
    assert isinstance(idxs, set)
    assert len(idxs) == body_slot_count(34) == 3
    assert all(isinstance(i, int) for i in idxs)


def test_body_ph_indices_empty_for_native() -> None:
    assert body_ph_indices(0) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_body_slot_count.py -v`
Expected: FAIL — `ImportError: cannot import name 'body_ph_indices' from 'graph.donor_map'`.

- [ ] **Step 3: Write minimal implementation**

In `graph/donor_map.py`, add immediately after `slot_name_by_ph_idx` (ends ~line 284):

```python
def body_ph_indices(layout_idx: int) -> set[int]:
    """Placeholder indices that map to body-type slots in a donor.

    Reuses ``_slot_name_to_ooxml`` (the same classifier the distributor
    trusts) so "body" capacity here matches what build_v9 actually fills.
    Native (``layout_idx == 0``) and unknown donors return an empty set.
    """
    if not layout_idx:
        return set()
    donor = _load().get(int(layout_idx))
    if donor is None:
        return set()
    out: set[int] = set()
    for name, slot in (donor.get("slots") or {}).items():
        if not isinstance(slot, dict):
            continue
        ph = slot.get("shape_idx")
        if ph is None:
            continue
        if _slot_name_to_ooxml(name) == "BODY":
            out.add(int(ph))
    return out


def body_slot_count(layout_idx: int) -> int:
    """Number of body-type slots a donor exposes (0 for native/unknown)."""
    return len(body_ph_indices(layout_idx))
```

Then extend `__all__` (line ~287) by adding the two names:

```python
__all__ = [
    "slot_specs_for_layouts",
    "slot_name_by_ph_idx",
    "body_ph_indices",
    "body_slot_count",
    "reload",
    "valid_donor_ids",
    "category_equivalence",
    "tone_groups",
    "default_donor_for_category",
    "donor_summary",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_body_slot_count.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add graph/donor_map.py tests/unit/test_body_slot_count.py
git commit -m "feat(donor_map): body-slot capacity helpers for sparse detector"
```

---

## Task 2: Sparse-slide detector (pure helper)

**Files:**
- Modify: `graph/nodes/agents.py` (add module-level helper + constant near the other deterministic helpers, after `_inject_visual_slides` which ends ~line 365, before `classify_node`)
- Test: `tests/unit/test_sparse_detector.py`

Detector contract — `_detect_sparse_slides(classification, layouts, content) -> list[dict]`:
- Keys each artefact's slides by `num` (classification/layouts) and `slide_num` (content).
- A content slide is inspected only if its classification entry has `category in {"text","multicolumn"}` and is NOT `_split_part`. All other categories (title/divider/image/logo/pattern_bg/team/timeline/callout/native types) are implicitly excluded by the positive `text`/`multicolumn` filter.
- `layout_idx` is read from the content slide (falls back to the layouts entry); `0`/falsy → native → skipped.
- `body_slots_total = donor_map.body_slot_count(layout_idx)`. Donors with `< 3` body slots are skipped (a 1–2-slot donor cannot be "underfilled").
- `body_slots_filled` = count of `placeholder_assignments` whose `ph_idx` is in `donor_map.body_ph_indices(layout_idx)` AND whose trimmed `content` is non-empty.
- Sparse iff `filled/total <= 0.50` OR (`total >= 4` and `filled <= 2`).
- Returns one diagnostics dict per sparse slide; empty list when none.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sparse_detector.py`:

```python
"""Phase-1 auto-structuring: deterministic sparse-slide detector.

Pure helper — no I/O beyond donor_map's cached slot-map read. Synthetic
artefact dicts model the four cases: sparse (flag), dense (skip),
exempt category (skip), split part (skip), small donor (skip).

Donor anchors (see plan): 34 = 3 body slots, 29 = 4 body slots,
28 = 2 body slots.
"""
from __future__ import annotations

from graph.nodes.agents import _detect_sparse_slides


def _cls(slides):
    return {"slides": slides}


def _content(slides):
    return {"slides": slides}


def _pa(ph_idx, content=""):
    return {"ph_idx": ph_idx, "ph_type": "BODY", "content": content}


def _layouts(slides):
    return {"slides": slides}


def test_sparse_3col_one_filled_is_flagged():
    # donor 34: 3 body slots; only 1 carries text → ratio 0.33 <= 0.5 → sparse.
    cls = _cls([{"num": 7, "category": "multicolumn"}])
    lay = _layouts([{"num": 7, "layout_idx": 34}])
    # ph_idx values for donor 34 body slots come from the live map; the
    # detector resolves which are body via donor_map.body_ph_indices, so we
    # fill exactly one real body slot and leave the rest empty.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    con = _content([{"slide_num": 7, "layout_idx": 34,
                     "placeholder_assignments": [
                         _pa(body[0], "Единственный реальный пункт."),
                         _pa(body[1], ""),
                         _pa(body[2], "   "),
                     ]}])
    out = _detect_sparse_slides(cls, lay, con)
    assert len(out) == 1
    d = out[0]
    assert d["num"] == 7
    assert d["body_slots_total"] == 3
    assert d["body_slots_filled"] == 1
    assert d["fill_ratio"] == 0.33


def test_dense_3col_all_filled_is_not_flagged():
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 8, "category": "multicolumn"}])
    lay = _layouts([{"num": 8, "layout_idx": 34}])
    con = _content([{"slide_num": 8, "layout_idx": 34,
                     "placeholder_assignments": [
                         _pa(body[0], "Раз."), _pa(body[1], "Два."),
                         _pa(body[2], "Три."),
                     ]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_4block_two_filled_is_flagged():
    # donor 29: 4 body slots, 2 filled → total>=4 and filled<=2 → sparse,
    # even though ratio (0.5) only just hits the boundary.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(29))
    cls = _cls([{"num": 5, "category": "multicolumn"}])
    lay = _layouts([{"num": 5, "layout_idx": 29}])
    con = _content([{"slide_num": 5, "layout_idx": 29,
                     "placeholder_assignments": [
                         _pa(body[0], "A"), _pa(body[1], "B"),
                         _pa(body[2], ""), _pa(body[3], ""),
                     ]}])
    out = _detect_sparse_slides(cls, lay, con)
    assert len(out) == 1
    assert out[0]["body_slots_total"] == 4
    assert out[0]["body_slots_filled"] == 2


def test_small_donor_two_body_slots_skipped():
    # donor 28: 2 body slots — below the >=3 floor, never inspected.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(28))
    cls = _cls([{"num": 9, "category": "multicolumn"}])
    lay = _layouts([{"num": 9, "layout_idx": 28}])
    con = _content([{"slide_num": 9, "layout_idx": 28,
                     "placeholder_assignments": [_pa(body[0], "Один."),
                                                 _pa(body[1], "")]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_exempt_category_image_skipped():
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 3, "category": "image"}])
    lay = _layouts([{"num": 3, "layout_idx": 34}])
    con = _content([{"slide_num": 3, "layout_idx": 34,
                     "placeholder_assignments": [_pa(body[0], "x")]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_split_part_skipped():
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 4, "category": "text", "_split_part": 2}])
    lay = _layouts([{"num": 4, "layout_idx": 34}])
    con = _content([{"slide_num": 4, "layout_idx": 34,
                     "placeholder_assignments": [_pa(body[0], "x")]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_native_slide_skipped():
    cls = _cls([{"num": 6, "category": "text"}])
    lay = _layouts([{"num": 6, "layout_idx": 0}])
    con = _content([{"slide_num": 6, "layout_idx": 0,
                     "placeholder_assignments": []}])
    assert _detect_sparse_slides(cls, lay, con) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_sparse_detector.py -v`
Expected: FAIL — `ImportError: cannot import name '_detect_sparse_slides' from 'graph.nodes.agents'`.

- [ ] **Step 3: Write minimal implementation**

In `graph/nodes/agents.py`, add after `_inject_visual_slides` (ends ~line 365) and before `def classify_node`:

```python
# Categories the sparse detector inspects. Everything else (title/divider/
# image/logo/pattern_bg/team/timeline/callout and all native slide_types)
# is intentionally light or specialised — never a sparse "flat donor" case.
_SPARSE_CATEGORIES = ("text", "multicolumn")
_SPARSE_MIN_BODY_SLOTS = 3


def _detect_sparse_slides(
    classification: dict[str, Any],
    layouts: dict[str, Any],
    content: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flag text/multicolumn slides that fill <= half of their donor's body
    slots — "lonely header over empty brand decoration".

    Telemetry-only (Phase 1): returns diagnostics, mutates nothing. Runs at
    the end of ``distribute_node`` where both the chosen donor (capacity) and
    the placed content (fill) are known. See spec §4.
    """
    from graph import donor_map  # noqa: WPS433 — local import keeps cycle clear

    cls_by_num: dict[int, dict[str, Any]] = {
        int(s.get("num", 0)): s for s in (classification.get("slides") or [])
    }
    lay_by_num: dict[int, dict[str, Any]] = {
        int(s.get("num", 0)): s for s in (layouts.get("slides") or [])
    }

    out: list[dict[str, Any]] = []
    for cs in (content.get("slides") or []):
        num = int(cs.get("slide_num", 0))
        cls = cls_by_num.get(num) or {}
        if cls.get("_split_part"):
            continue
        category = cls.get("category")
        if category not in _SPARSE_CATEGORIES:
            continue
        layout_idx = cs.get("layout_idx") or (lay_by_num.get(num) or {}).get("layout_idx") or 0
        if not layout_idx:  # native render — no donor to underfill
            continue
        layout_idx = int(layout_idx)
        total = donor_map.body_slot_count(layout_idx)
        if total < _SPARSE_MIN_BODY_SLOTS:
            continue
        body_idxs = donor_map.body_ph_indices(layout_idx)
        filled = 0
        chars: list[int] = []
        for pa in (cs.get("placeholder_assignments") or []):
            ph = pa.get("ph_idx")
            if ph is None or int(ph) not in body_idxs:
                continue
            text = (pa.get("content") or "").strip()
            if text:
                filled += 1
                chars.append(len(text))
        ratio = filled / total if total else 0.0
        sparse = (ratio <= 0.50) or (total >= 4 and filled <= 2)
        if not sparse:
            continue
        out.append({
            "num": num,
            "source_slide": cls.get("_source_slide") or num,
            "category": category,
            "layout_idx": layout_idx,
            "body_slots_total": total,
            "body_slots_filled": filled,
            "fill_ratio": round(ratio, 2),
            "real_item_count": filled,
            "content_chars": chars,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_sparse_detector.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add graph/nodes/agents.py tests/unit/test_sparse_detector.py
git commit -m "feat(classify): deterministic sparse-slide detector (telemetry helper)"
```

---

## Task 3: Wire detector into distribute_node (telemetry log)

**Files:**
- Modify: `graph/nodes/agents.py` — `distribute_node` (lines ~496-522)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_sparse_detector.py`:

```python
def test_distribute_node_logs_sparse_candidates(monkeypatch):
    """distribute_node calls the detector and logs when candidates exist,
    without altering arts['content']."""
    from graph.nodes import agents
    from graph import donor_map
    from llm.prompts import agent_03_content_distributor

    body = sorted(donor_map.body_ph_indices(34))
    classification = {"slides": [{"num": 7, "category": "multicolumn"}]}
    layouts = {"slides": [{"num": 7, "layout_idx": 34}]}
    content_dump = {"slides": [{"slide_num": 7, "layout_idx": 34,
                                "placeholder_assignments": [
                                    {"ph_idx": body[0], "ph_type": "BODY",
                                     "content": "Один пункт."},
                                    {"ph_idx": body[1], "ph_type": "BODY", "content": ""},
                                    {"ph_idx": body[2], "ph_type": "BODY", "content": ""},
                                ]}]}

    class _FakeContent:
        slides = [object()]  # len() only

        def model_dump(self):
            return content_dump

    # Run the node fully offline: no Redis publish, no prompt build, no LLM.
    monkeypatch.setattr(agents, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(agent_03_content_distributor, "build_messages",
                        lambda *a, **k: [])
    monkeypatch.setattr(agents, "call_and_parse",
                        lambda **kw: (_FakeContent(), None))

    logged = {}
    real_info = agents.logger.info

    def _capture(event, **kw):
        if event == "node.distribute.sparse_candidates":
            logged["count"] = kw.get("count")
        return real_info(event, **kw)

    monkeypatch.setattr(agents.logger, "info", _capture)

    state = _make_state(arts={
        "brief": {}, "classification": classification, "layouts": layouts,
    })
    patch = agents.distribute_node(state)

    assert patch["artefacts"]["content"] == content_dump  # unchanged
    assert logged.get("count") == 1


def _make_state(arts):
    """Minimal SessionState carrying artefacts (user_id/chat_id are required)."""
    from schemas.session import SessionState
    return SessionState(session_id="test-sparse", user_id=1, chat_id=1,
                        artefacts=arts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_sparse_detector.py::test_distribute_node_logs_sparse_candidates -v`
Expected: FAIL — assertion `logged.get("count") == 1` fails (the log line does not exist yet; `logged` is empty).

- [ ] **Step 3: Write minimal implementation**

In `graph/nodes/agents.py`, modify `distribute_node`. Locate (lines ~519-521):

```python
    arts["content"] = content.model_dump()
    logger.info("node.distribute.done", session_id=state.session_id,
                slides=len(content.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 50}
```

Replace with:

```python
    arts["content"] = content.model_dump()
    sparse = _detect_sparse_slides(
        classification, layouts, arts["content"])
    if sparse:
        logger.info(
            "node.distribute.sparse_candidates",
            session_id=state.session_id,
            count=len(sparse),
            slides=sparse,
        )
    logger.info("node.distribute.done", session_id=state.session_id,
                slides=len(content.slides),
                sparse_candidates=len(sparse))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 50}
```

Note: `classification` and `layouts` are already bound earlier in `distribute_node` (lines ~500-501).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_sparse_detector.py tests/unit/test_body_slot_count.py -v`
Expected: PASS (all green, incl. the new node test).

- [ ] **Step 5: Run the full unit suite for regressions**

Run: `python -m pytest tests/unit -q`
Expected: PASS — no previously-green test breaks (output diff for the pipeline is unchanged because the detector only logs).

- [ ] **Step 6: Commit**

```bash
git add graph/nodes/agents.py tests/unit/test_sparse_detector.py
git commit -m "feat(distribute): emit sparse-candidate telemetry (no mutation)"
```

---

## Task 4: Live telemetry run on Downloads decks + calibration notes

**Files:**
- No source changes. Produces logs + a short findings note appended to the spec.

This task validates Success Criteria §7: the detector enumerates genuinely underfilled slides on real decks and excludes healthy ones, with zero output change.

- [ ] **Step 1: Sync the changed files into the worker container**

```bash
cd "C:/Users/Глеб/Documents/Slides_bot"
for f in graph/donor_map.py graph/nodes/agents.py; do
  MSYS_NO_PATHCONV=1 docker exec -i slides-bot-worker sh -c "cat > /app/$f" < "$f"
done
```

- [ ] **Step 2: Run dl1/dl2/dl3 through the live pipeline**

```bash
for d in dl1 dl2 dl3; do
  MSYS_NO_PATHCONV=1 docker exec -d -w /app \
    -e LIVE_RUN_INPUT=/tmp/dl/$d.pptx slides-bot-worker \
    sh -c "python -m scripts.live_run > /tmp/dl/wlive_${d}_sparse.log 2>&1"
done
```

Then poll for completion (each log ends with a finalize/summary line):

Run: `MSYS_NO_PATHCONV=1 docker exec slides-bot-worker sh -c "tail -3 /tmp/dl/wlive_dl1_sparse.log /tmp/dl/wlive_dl2_sparse.log /tmp/dl/wlive_dl3_sparse.log"`
Expected: each run reaches finalize without traceback.

- [ ] **Step 2b: Wait for completion without polling in a sleep loop**

The runs were launched with `docker exec -d` (detached). Re-run the `tail -3` check from Step 2 once; if a run hasn't finished, check again after doing other review work — do not spin in a sleep loop.

- [ ] **Step 3: Extract the sparse-candidate telemetry**

Run: `MSYS_NO_PATHCONV=1 docker exec slides-bot-worker sh -c "grep -h sparse_candidates /tmp/dl/wlive_dl*_sparse.log"`
Expected: zero or more `node.distribute.sparse_candidates` lines with per-slide `num/body_slots_total/body_slots_filled/fill_ratio/content_chars`.

- [ ] **Step 4: Eyeball the flagged slides against the rendered PNGs**

For each flagged `num`, open the corresponding rendered slide PNG from the run's output (the live_run writes a deck + PNG sheet under `/tmp/dl/`; locate the latest run dir). Confirm by eye:
- flagged slides are genuinely underfilled (header + lots of empty brand decoration), AND
- well-filled / dense slides were NOT flagged (no false positives).

If the conservative §4.4 threshold over- or under-fires, record the observed counts and which slides to re-tune (do NOT change the threshold in this task — calibration feeds the Phase 2 spec).

- [ ] **Step 5: Append a "Phase 1 telemetry findings" section to the spec**

Edit `docs/superpowers/specs/2026-06-06-auto-structuring-sparse-slides-design.md`, adding a `## 8. Phase 1 Telemetry Findings (2026-06-06)` section with: per-deck count of sparse candidates, the slide numbers flagged, a one-line verdict on false-positive/false-negative rate, and the recommended starting threshold + remedy routing for the Phase 2 spec.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-06-06-auto-structuring-sparse-slides-design.md
git commit -m "docs(auto-structuring): Phase 1 telemetry findings from dl1/dl2/dl3"
```

---

## Done When
- `body_slot_count` / `body_ph_indices` exist, are in `__all__`, and their tests pass against the live slot map.
- `_detect_sparse_slides` is implemented, unit-tested over sparse/dense/exempt/split/small-donor/native fixtures, and wired into `distribute_node` as a telemetry-only log.
- The full `tests/unit` suite is green (no regressions; pipeline output unchanged).
- dl1/dl2/dl3 live runs emit `node.distribute.sparse_candidates` and the flagged slides are confirmed by eye to be the genuinely underfilled ones.
- Phase 1 findings + a recommended Phase 2 threshold/remedy are recorded in the spec.
