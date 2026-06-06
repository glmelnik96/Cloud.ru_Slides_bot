"""Pending-job dispatch: drain the global queue when the run-slot frees up.

The bot serialises all jobs through a single global lock (``bot.jobs``). When a
job reaches a terminal state the progress subscriber calls the callback built by
``make_on_terminal``: release the lock, then dispatch the next queued job.

Lives in its own module (not ``bot.handlers.verstai``) so both ``verstai`` and
``resume`` can share the same on-terminal/dispatch logic without an import
cycle through the progress subscriber.
"""
from __future__ import annotations

import structlog
from telegram.ext import Application

from bot.handlers.progress import start_subscriber
from bot.jobs import (
    claim_global_lock,
    dequeue_job,
    queue_length,
    release_global_lock,
    requeue_front,
    save_job,
)
from schemas.session import ProgressEvent, SessionInput

logger = structlog.get_logger(__name__)


def make_on_terminal(app: Application):
    """Build an on-terminal callback bound to *app*.

    On any terminal event it frees the global lock for the finished session and
    pulls the next queued job into the run-slot.
    """
    async def _on_terminal(event: ProgressEvent) -> None:
        release_global_lock(event.session_id)
        await dispatch_next(app)

    return _on_terminal


async def dispatch_next(app: Application) -> None:
    """Pop the next queued job, claim the lock, and start it running."""
    entry = dequeue_job()
    if entry is None:
        return
    session_id = entry["session_id"]
    if not claim_global_lock(session_id):
        # Another submission grabbed the slot between release and now. Put this
        # back at the head; that job's terminal event will re-trigger dispatch.
        requeue_front(entry)
        logger.info("queue.dispatch_deferred", session_id=session_id)
        return

    inp = SessionInput.model_validate(entry["input_json"])
    try:
        from worker.tasks.pipeline import run_pipeline
        async_result = run_pipeline.delay(inp.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001
        release_global_lock(session_id)
        logger.exception("queue.dispatch_failed", session_id=session_id, error=str(e))
        return

    save_job(
        session_id=session_id,
        user_id=entry["user_id"],
        chat_id=entry["chat_id"],
        message_id=entry["message_id"],
        task_id=async_result.id,
        mode=inp.mode.value,
    )
    start_subscriber(
        app,
        session_id=session_id,
        chat_id=entry["chat_id"],
        message_id=entry["message_id"],
        on_terminal=make_on_terminal(app),
    )
    logger.info(
        "queue.dispatched",
        session_id=session_id,
        task_id=async_result.id,
        queue_remaining=queue_length(),
    )
