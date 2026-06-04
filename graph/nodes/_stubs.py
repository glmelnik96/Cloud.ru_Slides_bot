"""M2 placeholder nodes. Each sleeps briefly and emits a progress event,
so the bot↔worker progress pipe can be exercised end-to-end before real
LLM/render nodes land in M3.
"""
from __future__ import annotations

import time

import structlog

from schemas.session import SessionState, Stage
from worker import progress

logger = structlog.get_logger(__name__)


def parse_stub(state: SessionState) -> dict:
    progress.stage(state.session_id, Stage.PARSING, pct=10, detail="чтение входа")
    time.sleep(1.5)
    logger.info("node.parse_stub.done", session_id=state.session_id)
    return {"stage": Stage.PARSING.value, "progress_pct": 10}


def process_stub(state: SessionState) -> dict:
    # Stand-in for the future classifier→designer→render loop.
    for pct, note in [(35, "анализ"), (60, "сборка"), (85, "проверка")]:
        progress.stage(state.session_id, Stage.DESIGNING, pct=pct, detail=note)
        time.sleep(1.0)
    logger.info("node.process_stub.done", session_id=state.session_id)
    return {"stage": Stage.DESIGNING.value, "progress_pct": 85}


def finalize_stub(state: SessionState) -> dict:
    progress.stage(state.session_id, Stage.FINALIZING, pct=95, detail="упаковка")
    time.sleep(0.5)
    progress.done(state.session_id, detail="готово")
    logger.info("node.finalize_stub.done", session_id=state.session_id)
    return {
        "stage": Stage.DONE.value,
        "progress_pct": 100,
        "notes": ["[M2 stub] результат сгенерирован без реального рендера"],
    }
