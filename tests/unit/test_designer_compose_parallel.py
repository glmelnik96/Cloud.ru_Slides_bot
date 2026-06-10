"""Parallel compose_node: parity with sequential, order, phantom-skip, speedup."""
from __future__ import annotations

import time
from typing import Any

import pytest

import graph.designer.nodes as nodes
from schemas.session import SessionState


def _state(n_slides: int) -> SessionState:
    cls_slides = [
        {"num": i + 1, "type": "text", "title": f"Слайд {i + 1}"}
        for i in range(n_slides)
    ]
    brief_slides = [
        {"num": i + 1, "raw_title": f"Слайд {i + 1}", "raw_body": [f"тезис {i + 1}"]}
        for i in range(n_slides)
    ]
    return SessionState(
        session_id="test-parallel",
        user_id=1, chat_id=1, progress_message_id=1,
        mode="design", created_at_iso="2026-06-10T00:00:00",
        artefacts={
            "design_stub": {"tonality": "strict", "dark_ratio": 0.2},
            "classification": {"slides": cls_slides},
            "brief": {"slides": brief_slides},
            "designer_vision_qa": False,  # vision QA mocked off — not under test
        },
    )


@pytest.fixture()
def mocked_compose(monkeypatch):
    """Deterministic per-slide compose with a small artificial latency."""
    delay = 0.15

    def fake_skeleton(stub, content, archetype, layouts, num):
        time.sleep(delay)
        return {"slide_num": num, "layout": layouts[0],
                "content": {"title": content.get("title") or ""}}

    def fake_one(stub, content, archetype, num, use_critic=True):
        time.sleep(delay)
        return {"slide_num": num, "blocks": [
            {"role": "title", "text": content.get("title") or ""},
            {"role": "body", "bullets": content.get("body") or []},
        ]}

    monkeypatch.setattr(nodes, "_compose_skeleton", fake_skeleton)
    monkeypatch.setattr(nodes, "_compose_one", fake_one)
    monkeypatch.setattr(nodes.progress, "stage", lambda *a, **k: None)
    return delay


def _run(monkeypatch, state: SessionState, workers: int) -> dict[str, Any]:
    monkeypatch.setattr(nodes, "COMPOSE_WORKERS", workers)
    return nodes.compose_node(state)


def test_parallel_matches_sequential(monkeypatch, mocked_compose):
    seq = _run(monkeypatch, _state(6), workers=1)
    par = _run(monkeypatch, _state(6), workers=4)
    assert par["artefacts"]["compositions"] == seq["artefacts"]["compositions"]


def test_order_preserved(monkeypatch, mocked_compose):
    out = _run(monkeypatch, _state(8), workers=4)
    nums = [c["slide_num"] for c in out["artefacts"]["compositions"]]
    assert nums == sorted(nums) == list(range(1, 9))


def test_phantom_slides_skipped(monkeypatch, mocked_compose):
    state = _state(4)
    arts = dict(state.artefacts)
    # Slide 3 has no text and no native content → phantom.
    arts["classification"]["slides"][2] = {"num": 3, "type": "text", "title": ""}
    arts["brief"]["slides"][2] = {"num": 3, "raw_title": "", "raw_body": []}
    state = state.model_copy(update={"artefacts": arts})
    out = _run(monkeypatch, state, workers=4)
    nums = [c["slide_num"] for c in out["artefacts"]["compositions"]]
    assert nums == [1, 2, 4]


def test_parallel_is_faster(monkeypatch, mocked_compose):
    n, delay = 8, mocked_compose
    t0 = time.perf_counter()
    _run(monkeypatch, _state(n), workers=1)
    t_seq = time.perf_counter() - t0

    t0 = time.perf_counter()
    _run(monkeypatch, _state(n), workers=4)
    t_par = time.perf_counter() - t0

    # 8 slides × 0.15s: sequential ≈ 1.2s, 4 workers ≈ 0.3s. Require ≥2×.
    assert t_seq >= n * delay * 0.9
    assert t_par < t_seq / 2, f"no speedup: seq={t_seq:.2f}s par={t_par:.2f}s"


def test_fallback_counted_once_per_degenerate_slide(monkeypatch, mocked_compose, caplog):
    # Force the free-grid path (no layouts) returning a title-only comp → fallback.
    monkeypatch.setattr(nodes, "layout_options", lambda *a, **k: [])
    monkeypatch.setattr(
        nodes, "_compose_one",
        lambda stub, content, archetype, num, use_critic=True: {
            "slide_num": num,
            "blocks": [{"role": "title", "text": "t"}],
        },
    )
    out = _run(monkeypatch, _state(3), workers=4)
    assert len(out["artefacts"]["compositions"]) == 3
