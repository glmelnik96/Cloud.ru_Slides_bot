"""Phase-2A auto-structuring: deterministic sparse-slide detector (volume).

Pure helper — no I/O beyond donor_map's cached slot-map read. The signal is
per-slot WORD volume, not occupancy: a flat-donor slide is flagged when a body
slot carries trivially little text (<= 2 words), even at full slot occupancy
(the "lonely header over empty decoration" case occupancy missed). Timeline
donors (variable-length roadmaps) are exempt.

Donor anchors: 34 = 3 body slots, 29 = 4 body slots, 28 = 2 body slots,
60 = timeline (step1_body … step10_body).
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


def test_full_occupancy_but_thin_is_flagged():
    # donor 34: all 3 body slots filled (occupancy 1.0 — Phase 1 saw this as
    # healthy) but each carries <= 2 words → thin_slot_count 3 → flagged.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 7, "category": "multicolumn"}])
    lay = _layouts([{"num": 7, "layout_idx": 34}])
    con = _content([{"slide_num": 7, "layout_idx": 34,
                     "placeholder_assignments": [
                         _pa(body[0], "Альфа"),
                         _pa(body[1], "Бета гамма"),
                         _pa(body[2], "Дельта"),
                     ]}])
    out = _detect_sparse_slides(cls, lay, con)
    assert len(out) == 1
    d = out[0]
    assert d["num"] == 7
    assert d["body_slots_total"] == 3
    assert d["body_slots_filled"] == 3
    assert d["thin_slot_count"] == 3
    assert d["body_words_per_slot"] == [1, 2, 1]
    assert d["body_word_total"] == 4
    assert "fill_ratio" not in d


def test_one_thin_slot_is_flagged():
    # Two dense slots + one 1-word slot → thin_slot_count 1 → flagged.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 8, "category": "multicolumn"}])
    lay = _layouts([{"num": 8, "layout_idx": 34}])
    con = _content([{"slide_num": 8, "layout_idx": 34,
                     "placeholder_assignments": [
                         _pa(body[0], "Полноценный пункт с описанием здесь."),
                         _pa(body[1], "Ещё один пункт с текстом."),
                         _pa(body[2], "Слово"),
                     ]}])
    out = _detect_sparse_slides(cls, lay, con)
    assert len(out) == 1
    assert out[0]["thin_slot_count"] == 1


def test_dense_3col_is_not_flagged():
    # Every filled body slot has >= 3 words → thin_slot_count 0 → not flagged.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(34))
    cls = _cls([{"num": 9, "category": "multicolumn"}])
    lay = _layouts([{"num": 9, "layout_idx": 34}])
    con = _content([{"slide_num": 9, "layout_idx": 34,
                     "placeholder_assignments": [
                         _pa(body[0], "Первый содержательный пункт."),
                         _pa(body[1], "Второй содержательный пункт."),
                         _pa(body[2], "Третий содержательный пункт."),
                     ]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_timeline_donor_is_exempt():
    # donor 60: thin slots, but a roadmap is sparse by design → never flagged.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(60))
    cls = _cls([{"num": 4, "category": "multicolumn"}])
    lay = _layouts([{"num": 4, "layout_idx": 60}])
    con = _content([{"slide_num": 4, "layout_idx": 60,
                     "placeholder_assignments": [
                         _pa(body[0], "Шаг"), _pa(body[1], "Этап"),
                         _pa(body[2], "Фаза"),
                     ]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_small_donor_two_body_slots_skipped():
    # donor 28: 2 body slots — below the >=3 floor, never inspected.
    from graph import donor_map
    body = sorted(donor_map.body_ph_indices(28))
    cls = _cls([{"num": 5, "category": "multicolumn"}])
    lay = _layouts([{"num": 5, "layout_idx": 28}])
    con = _content([{"slide_num": 5, "layout_idx": 28,
                     "placeholder_assignments": [_pa(body[0], "Раз"),
                                                 _pa(body[1], "Два")]}])
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
    cls = _cls([{"num": 6, "category": "text", "_split_part": 2}])
    lay = _layouts([{"num": 6, "layout_idx": 34}])
    con = _content([{"slide_num": 6, "layout_idx": 34,
                     "placeholder_assignments": [_pa(body[0], "x")]}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_native_slide_skipped():
    cls = _cls([{"num": 2, "category": "text"}])
    lay = _layouts([{"num": 2, "layout_idx": 0}])
    con = _content([{"slide_num": 2, "layout_idx": 0,
                     "placeholder_assignments": []}])
    assert _detect_sparse_slides(cls, lay, con) == []


def test_distribute_node_logs_sparse_volume(monkeypatch):
    """distribute_node calls the detector and logs node.distribute.sparse_volume
    when thin slides exist, without altering arts['content']."""
    from graph.nodes import agents
    from graph import donor_map
    from llm.prompts import agent_03_content_distributor

    body = sorted(donor_map.body_ph_indices(34))
    classification = {"slides": [{"num": 7, "category": "multicolumn"}]}
    layouts = {"slides": [{"num": 7, "layout_idx": 34}]}
    content_dump = {"slides": [{"slide_num": 7, "layout_idx": 34,
                                "placeholder_assignments": [
                                    {"ph_idx": body[0], "ph_type": "BODY",
                                     "content": "Слово"},
                                    {"ph_idx": body[1], "ph_type": "BODY",
                                     "content": "Два слова"},
                                    {"ph_idx": body[2], "ph_type": "BODY",
                                     "content": "Тут"},
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
        if event == "node.distribute.sparse_volume":
            logged["count"] = kw.get("count")
        return real_info(event, **kw)

    monkeypatch.setattr(agents.logger, "info", _capture)

    state = _make_state(arts={
        "brief": {}, "classification": classification, "layouts": layouts,
    })
    patch = agents.distribute_node(state)

    assert patch["artefacts"]["content"] == content_dump  # unchanged
    assert logged.get("count") == 1
