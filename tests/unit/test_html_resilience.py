"""Resilience fixes after the 2026-06-10 live incident (hung /html run + 503 storm).

Three layers:
1. llm/client retry predicate — 5xx/429/408/connection errors are transient
   (retried with long backoff), other 4xx are caller bugs (fail fast).
2. renderers/html/qa fail-open gates must NOT swallow Celery's soft time limit
   (that's what turned a slow run into a 1h hard-kill hang with no terminal
   progress event).
3. graph/html compose node — parallel per-slide fan-out with a wall-clock
   budget: slides starting past the deadline run compose-only fast mode so the
   deck always finishes inside the soft limit.
"""
from __future__ import annotations

import threading

import httpx
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from openai import APIConnectionError, APIStatusError

from llm.client import _is_transient_api_error


# ─── 1. retry predicate ─────────────────────────────────────────────────────

def _status_error(code: int) -> APIStatusError:
    req = httpx.Request("POST", "http://cloud.ru/v1/chat/completions")
    resp = httpx.Response(code, request=req, text="err")
    return APIStatusError("err", response=resp, body=None)


@pytest.mark.parametrize("code", [500, 502, 503, 504, 429, 408, 409])
def test_transient_status_codes_are_retried(code):
    assert _is_transient_api_error(_status_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_caller_bug_status_codes_fail_fast(code):
    assert _is_transient_api_error(_status_error(code)) is False


def test_connection_error_is_retried():
    req = httpx.Request("POST", "http://cloud.ru/v1/chat/completions")
    assert _is_transient_api_error(APIConnectionError(request=req)) is True


def test_unrelated_exception_not_retried():
    assert _is_transient_api_error(ValueError("boom")) is False


# ─── 2. QA gates must propagate the soft time limit ──────────────────────────

def test_critic_gate_propagates_soft_timeout(monkeypatch):
    from renderers.html import qa

    def _boom(**kw):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(qa, "call_and_parse", _boom)
    with pytest.raises(SoftTimeLimitExceeded):
        qa.critic_gate("<div></div>", {})


def test_critic_gate_still_fails_open_on_llm_error(monkeypatch):
    from renderers.html import qa

    def _boom(**kw):
        raise ValueError("flaky judge")

    monkeypatch.setattr(qa, "call_and_parse", _boom)
    assert qa.critic_gate("<div></div>", {}).verdict == "READY"


def test_judge_slide_propagates_soft_timeout(monkeypatch):
    from renderers.html import qa

    def _boom(**kw):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(qa, "call_and_parse", _boom)
    monkeypatch.setattr(qa.pixel_judge, "build_messages", lambda *a, **k: [])
    with pytest.raises(SoftTimeLimitExceeded):
        qa.judge_slide({}, b"png", "title-body")


def test_judge_slide_still_fails_open_on_llm_error(monkeypatch):
    from renderers.html import qa

    def _boom(**kw):
        raise ValueError("flaky judge")

    monkeypatch.setattr(qa, "call_and_parse", _boom)
    monkeypatch.setattr(qa.pixel_judge, "build_messages", lambda *a, **k: [])
    assert qa.judge_slide({}, b"png", "title-body").ok is True


# ─── 3. compose node: parallel fan-out + time budget ─────────────────────────

class _FakeRenderer:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def render(self, body):  # noqa: ARG002
        return b"\x89PNG-fake"


def _make_state(n_slides: int):
    from schemas.session import SessionInput, SessionState
    inp = SessionInput(
        session_id="test-html", user_id=1, chat_id=1,
        progress_message_id=0, mode="html", input_s3_key=None,
    )
    s = SessionState.from_input(inp)
    classification = {"slides": [{"num": i + 1} for i in range(n_slides)]}
    return s.model_copy(update={"artefacts": {"classification": classification}})


@pytest.fixture()
def offline_nodes(monkeypatch, tmp_path):
    from graph.html import nodes

    calls = {"critic": 0, "judge": 0, "compose": 0}
    lock = threading.Lock()

    class _Ready:
        verdict = "READY"
        reasons: list[str] = []

    class _Ok:
        ok = True
        issues: list[str] = []

    def _critic(body, payload):  # noqa: ARG001
        with lock:
            calls["critic"] += 1
        return _Ready()

    def _judge(payload, png, archetype):  # noqa: ARG001
        with lock:
            calls["judge"] += 1
        return _Ok()

    def _compose(payload, css, feedback=None):  # noqa: ARG001
        with lock:
            calls["compose"] += 1
        return f"<div class='slide'>{payload.get('title', '')}</div>"

    monkeypatch.setattr(nodes, "SlideRenderer", _FakeRenderer)
    monkeypatch.setattr(nodes, "load_brand_css", lambda: "css")
    monkeypatch.setattr(nodes, "critic_gate", _critic)
    monkeypatch.setattr(nodes, "judge_slide", _judge)
    monkeypatch.setattr(nodes, "compose_slide", _compose)
    monkeypatch.setattr(nodes, "snap_payload", lambda p, parsed: p)
    monkeypatch.setattr(nodes, "archetype_for", lambda cls, is_first=False: "title-body")
    monkeypatch.setattr(
        nodes, "slide_content_for",
        lambda cls, brief: {"title": f"Слайд {cls['num']}", "body": ["x"]},
    )
    monkeypatch.setattr(nodes, "_session_workdir", lambda sid: tmp_path)
    monkeypatch.setattr(nodes, "_emit", lambda *a, **k: None)
    return nodes, calls


def test_compose_node_parallel_preserves_slide_order(offline_nodes, monkeypatch):
    nodes, calls = offline_nodes
    monkeypatch.setattr(nodes, "HTML_COMPOSE_WORKERS", 3)
    patch = nodes.html_compose_node(_make_state(5))
    paths = patch["artefacts"]["html_png_paths"]
    from pathlib import Path
    assert [Path(p).name for p in paths] == [f"html_s{i:02d}.png" for i in range(1, 6)]
    # Full QA ran for every slide.
    assert calls["critic"] == 5
    assert calls["judge"] == 5
    assert patch["progress_pct"] == 90


def test_compose_node_budget_exceeded_skips_qa_gates(offline_nodes, monkeypatch):
    nodes, calls = offline_nodes
    monkeypatch.setattr(nodes, "HTML_COMPOSE_WORKERS", 2)
    monkeypatch.setattr(nodes, "HTML_COMPOSE_BUDGET_S", -1.0)  # already past deadline
    patch = nodes.html_compose_node(_make_state(4))
    # Fast mode: compose once per slide, NO critic / vision judge calls.
    assert calls["compose"] == 4
    assert calls["critic"] == 0
    assert calls["judge"] == 0
    assert len(patch["artefacts"]["html_png_paths"]) == 4


def test_compose_node_sequential_path_still_works(offline_nodes, monkeypatch):
    nodes, calls = offline_nodes
    monkeypatch.setattr(nodes, "HTML_COMPOSE_WORKERS", 1)
    patch = nodes.html_compose_node(_make_state(2))
    assert len(patch["artefacts"]["html_png_paths"]) == 2
    assert calls["critic"] == 2
