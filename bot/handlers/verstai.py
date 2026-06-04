"""`/verstai` — enqueue a layout job.

M2 scope: any invocation enqueues a fake pipeline (stub nodes) and shows live
progress. Real .pptx ingestion lands in M3 together with the parsing node.
"""
from __future__ import annotations

import structlog
from telegram import Document, Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.handlers.progress import cancel_keyboard, start_subscriber
from bot.i18n.progress import format_progress
from bot.i18n.ru import VERSTAI_BAD_TYPE, VERSTAI_NEED_FILE
from bot.jobs import claim_user_lock, release_user_lock, save_job
from bot.middleware.whitelist import guarded
from schemas.session import Mode, SessionInput

logger = structlog.get_logger(__name__)

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _find_document(msg: Message) -> Document | None:
    """Look for an attached document in the current message, then in the replied-to."""
    if msg.document is not None:
        return msg.document
    if msg.reply_to_message is not None and msg.reply_to_message.document is not None:
        return msg.reply_to_message.document
    return None


def _is_pptx(doc: Document) -> bool:
    name = (doc.file_name or "").lower()
    return name.endswith(".pptx") or doc.mime_type == _PPTX_MIME


@guarded
async def verstai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id

    doc = _find_document(update.message)
    if doc is None:
        await update.message.reply_text(VERSTAI_NEED_FILE, parse_mode=ParseMode.HTML)
        return
    if not _is_pptx(doc):
        await update.message.reply_text(VERSTAI_BAD_TYPE, parse_mode=ParseMode.HTML)
        return

    inp = SessionInput(
        user_id=user.id,
        chat_id=chat_id,
        progress_message_id=0,  # filled in after we send the status message
        mode=Mode.VERSTAI,
        # M3: download via context.bot.get_file(doc.file_id) → upload to S3 → set key.
        # In M2 we accept the file as a UX signal but don't persist it yet.
        input_s3_key=None,
    )

    if not claim_user_lock(user.id, inp.session_id):
        await update.message.reply_text(
            "У вас уже идёт задача. Дождитесь её завершения или отмените."
        )
        return

    status_msg = await update.message.reply_text(
        format_progress("queued", 0, "ожидание воркера"),
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_keyboard(inp.session_id),
    )
    inp = inp.model_copy(update={"progress_message_id": status_msg.message_id})

    try:
        from worker.tasks.pipeline import run_pipeline
        async_result = run_pipeline.delay(inp.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001
        release_user_lock(user.id, inp.session_id)
        logger.exception("verstai.enqueue_failed", error=str(e))
        await update.message.reply_text("Не удалось поставить задачу. Попробуйте позже.")
        return

    save_job(
        session_id=inp.session_id,
        user_id=user.id,
        chat_id=chat_id,
        message_id=status_msg.message_id,
        task_id=async_result.id,
        mode=inp.mode.value,
    )

    async def _on_terminal(_event) -> None:
        # Always free the single-task lock once the pipeline ends (done/failed/cancelled).
        release_user_lock(user.id, inp.session_id)

    start_subscriber(
        context.application,
        session_id=inp.session_id,
        chat_id=chat_id,
        message_id=status_msg.message_id,
        on_terminal=_on_terminal,
    )
    logger.info(
        "verstai.enqueued",
        session_id=inp.session_id,
        task_id=async_result.id,
        user_id=user.id,
    )
