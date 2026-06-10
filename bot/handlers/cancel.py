"""Cancel paths: the inline button (callback `cancel:<sid>`) and the
`/cancel` command. Both revoke the Celery task, publish a cancelled event so
the progress subscriber updates the message, and release the per-user lock.
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.jobs import get_active_session_for_user, load_job, release_user_lock
from bot.middleware.whitelist import guarded
from worker import progress

logger = structlog.get_logger(__name__)


def _cancel_session(session_id: str) -> dict | None:
    """Common cancel logic. Returns the job dict if cancellation was issued."""
    job = load_job(session_id)
    if job is None:
        logger.warning("cancel.unknown_session", session_id=session_id)
        return None
    # Revoke the Celery task. SIGTERM lets the worker run try/finally cleanup
    # (e.g. soffice tmp dirs) before exiting.
    from worker.celery_app import app as celery_app
    celery_app.control.revoke(job["task_id"], terminate=True, signal="SIGTERM")
    logger.info("cancel.revoked", session_id=session_id, task_id=job["task_id"])
    # Publishing the cancelled event lets the live progress subscriber run its
    # on-terminal hook (release the per-user lock + dispatch the next queued
    # job). We also release here directly as a safety net in case no subscriber
    # is listening (e.g. after a bot restart); release is idempotent.
    progress.cancelled(session_id)
    release_user_lock(job["user_id"], session_id)
    return job


@guarded
async def cancel_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith("cancel:"):
        return
    session_id = query.data.split(":", 1)[1]
    await query.answer("Останавливаю…")
    _cancel_session(session_id)


@guarded
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/cancel` — kill the user's active task without needing the inline button."""
    user_id = update.effective_user.id
    active = get_active_session_for_user(user_id)
    if active is None:
        await update.message.reply_text("Нет активной задачи.")
        return
    if _cancel_session(active) is None:
        # Lock pointed at a session whose job record is gone — clean it up.
        release_user_lock(user_id, active)
        await update.message.reply_text("Лок снят, активной задачи не было.")
        return
    await update.message.reply_text("Останавливаю задачу…")
