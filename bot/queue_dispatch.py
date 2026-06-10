"""Pending-job dispatch: drain the queue when a per-user run-slot frees up.

Each user has their own run-slot (``bot.jobs`` per-user lock). When a job
reaches a terminal state the progress subscriber calls the callback built by
``make_on_terminal``: release the user lock, then dispatch the next queued job.

Lives in its own module (not ``bot.handlers.verstai``) so both ``verstai`` and
``resume`` can share the same on-terminal/dispatch logic without an import
cycle through the progress subscriber.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog
from telegram.ext import Application

from bot.handlers.progress import start_subscriber
from bot.jobs import (
    claim_user_lock,
    dequeue_job,
    enqueue_job,
    get_active_session,
    get_all_active_user_sessions,
    load_job,
    queue_length,
    release_global_lock,
    release_user_lock,
    requeue_front,
    save_job,
)
from schemas.session import Mode, ProgressEvent, SessionInput

logger = structlog.get_logger(__name__)

# Same shared inputs volume the bot downloads uploads into (see
# bot/handlers/verstai.py). Defined here too — importing it from verstai would
# create a cycle (verstai imports this module for ``make_on_terminal``).
_INPUTS_ROOT = Path(
    os.environ.get("SLIDESBOT_INPUTS_DIR")
    or (Path(tempfile.gettempdir()) / "slidesbot" / "inputs")
)


def make_on_terminal(app: Application):
    """Build an on-terminal callback bound to *app*.

    On any terminal event it frees the per-user lock for the finished session
    and pulls the next queued job into the run-slot.
    """
    async def _on_terminal(event: ProgressEvent) -> None:
        # Derive user_id from the stored job metadata so we can release the
        # correct per-user lock key (the event only carries session_id).
        job = load_job(event.session_id)
        if job is not None:
            release_user_lock(job["user_id"], event.session_id)
        await dispatch_next(app)

    return _on_terminal


def requeue_interrupted(session_id: str) -> str | None:
    """Re-enqueue an orphaned (locked-but-no-subscriber) job at the queue TAIL
    as a FRESH session, reusing its already-downloaded input file.

    Used by startup recovery: a restart drops every in-memory subscriber, so the
    job that held the run-slot can never reach its terminal event — we reprocess
    it from scratch, but behind whatever was already waiting (per the operator's
    "put the interrupted one at the end" instruction). A fresh ``session_id``
    avoids colliding with the dead run's RedisSaver checkpoint. Returns the new
    session_id, or None when the job metadata or input file is gone.
    """
    job = load_job(session_id)
    if job is None:
        logger.warning("queue.recover.no_job", session_id=session_id)
        return None
    input_path = _INPUTS_ROOT / f"{session_id}.pptx"
    if not input_path.exists():
        logger.warning("queue.recover.no_input",
                       session_id=session_id, path=str(input_path))
        return None
    inp = SessionInput(
        user_id=job["user_id"],
        chat_id=job["chat_id"],
        progress_message_id=job["message_id"],
        mode=Mode(job["mode"]),
        input_s3_key=str(input_path),
    )
    enqueue_job({
        "session_id": inp.session_id,
        "user_id": job["user_id"],
        "chat_id": job["chat_id"],
        "message_id": job["message_id"],
        "input_json": inp.model_dump(mode="json"),
    })
    logger.info("queue.recover.requeued_interrupted",
                old_session=session_id, new_session=inp.session_id)
    return inp.session_id


async def recover_queue_on_startup(app: Application) -> None:
    """PTB ``post_init`` hook: resume a queue stranded by a bot restart.

    No subscriber survives a restart, so any held per-user lock is orphaned —
    its ``on_terminal`` (lock-release + queue advance) will never fire. Re-queue
    interrupted jobs at the TAIL, free their slots, then dispatch the head so
    the backlog drains. Runs before polling starts, so there's no submission
    race.

    Also handles the legacy global lock key (``global_job_lock``) left by
    deployments that ran the old single-slot code.
    """
    # --- Legacy global lock (pre-per-user-lock deployments) ---
    legacy_active = get_active_session()
    if legacy_active is not None:
        requeue_interrupted(legacy_active)
        release_global_lock(legacy_active)
        logger.info("queue.recover.legacy_lock_released", session_id=legacy_active)

    # --- Per-user locks ---
    for user_id, session_id in get_all_active_user_sessions():
        requeue_interrupted(session_id)
        release_user_lock(user_id, session_id)
        logger.info("queue.recover.user_lock_released",
                    user_id=user_id, session_id=session_id)

    if queue_length() > 0:
        await dispatch_next(app)


async def dispatch_next(app: Application) -> None:
    """Pop the next queued job, claim the per-user lock, and start it running."""
    entry = dequeue_job()
    if entry is None:
        return
    session_id = entry["session_id"]
    user_id = entry["user_id"]
    if not claim_user_lock(user_id, session_id):
        # This user already has a job in flight (e.g. submitted via another
        # path between release and now). Put this back at the head; that job's
        # terminal event will re-trigger dispatch.
        requeue_front(entry)
        logger.info("queue.dispatch_deferred", session_id=session_id, user_id=user_id)
        return

    inp = SessionInput.model_validate(entry["input_json"])
    try:
        from worker.tasks.pipeline import run_pipeline
        async_result = run_pipeline.delay(inp.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001
        release_user_lock(user_id, session_id)
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
