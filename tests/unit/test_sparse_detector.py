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


def _make_state(arts):
    """Minimal SessionState carrying artefacts (user_id/chat_id are required)."""
    from schemas.session import SessionInput, SessionState
    inp = SessionInput(
        session_id="test-sparse", user_id=1, chat_id=1,
        progress_message_id=0, mode="verstai", input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    return s.model_copy(update={"artefacts": dict(arts)})


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
    # donor 29: 4 body slots, 2 filled → ratio exactly 0.50, caught by the
    # ratio clause. (The total>=4/filled<=2 clause is spec-required but adds
    # no coverage over the ratio clause for integer slot counts.)
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
