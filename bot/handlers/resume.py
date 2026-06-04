"""`/resume <session_id>` — re-enqueue a job that was halted, cancelled, or
crashed. The LangGraph RedisSaver remembers where we stopped.
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.handlers.progress import start_subscriber
from bot.i18n.progress import format_progress
from bot.jobs import claim_user_lock, load_job, release_user_lock, save_job, update_job_task_id
from bot.middleware.whitelist import guarded

logger = structlog.get_logger(__name__)


@guarded
async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Использование: <code>/resume &lt;session_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    session_id = context.args[0].strip()
    job = load_job(session_id)
    if job is None:
        await update.message.reply_text(
            "Сессия не найдена или истекла (TTL 7 дней)."
        )
        return
    if job["user_id"] != update.effective_user.id:
        await update.message.reply_text("Эта сессия принадлежит другому пользователю.")
        return

    if not claim_user_lock(update.effective_user.id, session_id):
        await update.message.reply_text(
            "У вас уже идёт другая задача. Отмените её перед возобновлением."
        )
        return

    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text(
        format_progress("queued", 0, "возобновление сессии"),
        parse_mode=ParseMode.HTML,
    )

    from worker.tasks.pipeline import resume_pipeline
    async_result = resume_pipeline.delay(session_id, status_msg.message_id, chat_id)
    update_job_task_id(session_id, async_result.id)
    save_job(
        session_id=session_id,
        user_id=update.effective_user.id,
        chat_id=chat_id,
        message_id=status_msg.message_id,
        task_id=async_result.id,
        mode=job["mode"],
    )
    async def _on_terminal(_event) -> None:
        release_user_lock(update.effective_user.id, session_id)

    start_subscriber(
        context.application,
        session_id=session_id,
        chat_id=chat_id,
        message_id=status_msg.message_id,
        on_terminal=_on_terminal,
    )
    logger.info("resume.enqueued", session_id=session_id, task_id=async_result.id)
