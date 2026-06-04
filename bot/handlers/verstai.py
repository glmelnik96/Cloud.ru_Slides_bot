"""`/verstai` — enqueue a layout job.

M3 scope: the uploaded .pptx is downloaded to a local temp file and its path
is threaded through ``SessionInput.input_s3_key`` for the worker. Real S3
upload lands in M5; until then ``input_s3_key`` carries a local filesystem
path (worker and bot share the same machine in M3).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import structlog
from telegram import Document, Message, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.handlers.progress import cancel_keyboard, start_subscriber
from bot.i18n.progress import format_progress
from bot.i18n.ru import VERSTAI_BAD_TYPE, VERSTAI_NEED_FILE
from bot.jobs import claim_user_lock, release_user_lock, save_job
from bot.middleware.whitelist import guarded
from schemas.session import Mode, SessionInput

logger = structlog.get_logger(__name__)

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Telegram Bot API caps document downloads at 20 MiB unless you run a local
# Bot API server. Reject early with a clear message rather than letting the
# download fail mid-stream.
_MAX_PPTX_BYTES = 20 * 1024 * 1024

# Shared root with worker-side _session_workdir (graph.nodes.pipeline) so the
# orchestrator can place plan.json / built.pptx / pngs alongside the input.
_INPUTS_ROOT = Path(tempfile.gettempdir()) / "slidesbot" / "inputs"


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
    if doc.file_size and doc.file_size > _MAX_PPTX_BYTES:
        await update.message.reply_text(
            f"Файл слишком большой ({doc.file_size / 1024 / 1024:.1f} МБ). "
            f"Лимит Telegram Bot API — 20 МБ."
        )
        return

    inp = SessionInput(
        user_id=user.id,
        chat_id=chat_id,
        progress_message_id=0,  # filled in after we send the status message
        mode=Mode.VERSTAI,
        # M5 will upload to S3 and set a real key here. M3 interim: download
        # to a stable local path and pass the absolute path through this same
        # field. parse_node (graph/nodes/pipeline.py) treats a non-empty value
        # as a local path until S3 lands, so the field name doesn't churn.
        input_s3_key=None,
    )

    # Claim the single-task lock BEFORE the download so a double-tap doesn't
    # trigger two Telegram fetches.
    if not claim_user_lock(user.id, inp.session_id):
        await update.message.reply_text(
            "У вас уже идёт задача. Дождитесь её завершения или отмените."
        )
        return

    # Download the .pptx before we enqueue — if Telegram throws we want to fail
    # fast with a clear message instead of the worker discovering it later.
    _INPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    local_path = _INPUTS_ROOT / f"{inp.session_id}.pptx"
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=str(local_path))
    except TelegramError as e:
        release_user_lock(user.id, inp.session_id)
        logger.exception("verstai.download_failed", error=str(e),
                         session_id=inp.session_id, file_id=doc.file_id)
        await update.message.reply_text(
            "Не удалось скачать файл из Telegram. Попробуйте отправить ещё раз."
        )
        return
    inp = inp.model_copy(update={"input_s3_key": str(local_path)})

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
