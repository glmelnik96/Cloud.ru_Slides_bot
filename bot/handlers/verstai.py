"""`/verstai` — enqueue a layout job.

M3 scope: the uploaded .pptx is downloaded to a local temp file and its path
is threaded through ``SessionInput.input_s3_key`` for the worker. Real S3
upload lands in M5; until then ``input_s3_key`` carries a local filesystem
path (worker and bot share the same machine in M3).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog
from telegram import Document, Message, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from bot.handlers.progress import start_subscriber
from bot.i18n.progress import format_progress
from bot.i18n.ru import VERSTAI_BAD_TYPE, VERSTAI_NEED_FILE
from bot.jobs import claim_user_lock, enqueue_job, release_user_lock, save_job
from bot.middleware.whitelist import guarded
from bot.queue_dispatch import make_on_terminal
from schemas.session import Mode, SessionInput

logger = structlog.get_logger(__name__)

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Telegram Bot API caps document downloads at 20 MiB unless you run a local
# Bot API server. Reject early with a clear message rather than letting the
# download fail mid-stream.
_MAX_PPTX_BYTES = 20 * 1024 * 1024

# Shared root with worker-side _session_workdir (graph.nodes.pipeline) so the
# orchestrator can place plan.json / built.pptx / pngs alongside the input.
#
# Bot and worker live in *different* containers in prod — the path that the
# bot writes to must be visible to the worker. The Docker Compose file mounts
# a named volume at `/var/lib/slidesbot/inputs` in both containers and sets
# `SLIDESBOT_INPUTS_DIR` to that path; on the host (live_run, tests) the env
# var is unset and we fall back to OS temp.
_INPUTS_ROOT = Path(
    os.environ.get("SLIDESBOT_INPUTS_DIR")
    or (Path(tempfile.gettempdir()) / "slidesbot" / "inputs")
)


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


async def _dispatch_pptx_job(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, mode: Mode, log_prefix: str,
) -> None:
    """Shared pptx-upload → enqueue flow for the .pptx-driven modes.

    /verstai (donor pipeline) and /design (from-scratch designer) take the same
    input — a .pptx — and differ only by the ``mode`` threaded into SessionInput
    and the log namespace. Everything else (download, size cap, global run-slot,
    queue, progress subscriber) is identical.
    """
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
        mode=mode,
        # M5 will upload to S3 and set a real key here. M3 interim: download
        # to a stable local path and pass the absolute path through this same
        # field. parse_node (graph/nodes/pipeline.py) treats a non-empty value
        # as a local path until S3 lands, so the field name doesn't churn.
        input_s3_key=None,
        source_filename=doc.file_name,
    )

    # Download the .pptx up front — a queued job needs its input on disk ready
    # for whenever the run-slot frees up. If Telegram throws we fail fast with a
    # clear message instead of the worker discovering it later.
    _INPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    local_path = _INPUTS_ROOT / f"{inp.session_id}.pptx"
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(custom_path=str(local_path))
    except TelegramError as e:
        logger.exception(f"{log_prefix}.download_failed", error=str(e),
                         session_id=inp.session_id, file_id=doc.file_id)
        await update.message.reply_text(
            "Не удалось скачать файл из Telegram. Попробуйте отправить ещё раз."
        )
        return
    inp = inp.model_copy(update={"input_s3_key": str(local_path)})

    status_msg = await update.message.reply_text(
        format_progress("queued", 0, "ожидание воркера"),
        parse_mode=ParseMode.HTML,
    )
    inp = inp.model_copy(update={"progress_message_id": status_msg.message_id})

    # Per-user run-slot: if it's free we start immediately, otherwise the job
    # waits its turn in the queue and is dispatched on the active job's terminal.
    if not claim_user_lock(user.id, inp.session_id):
        entry = {
            "session_id": inp.session_id,
            "user_id": user.id,
            "chat_id": chat_id,
            "message_id": status_msg.message_id,
            "input_json": inp.model_dump(mode="json"),
        }
        position = enqueue_job(entry)
        if position == 0:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id,
                text="Очередь заполнена (максимум 10). Попробуйте позже.",
            )
            return
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=status_msg.message_id,
            text=f"⏳ У вас уже идёт сборка, позиция в очереди {position}. Начну, как завершится текущая.",
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"{log_prefix}.queued", session_id=inp.session_id,
                    user_id=user.id, position=position)
        return

    try:
        from worker.tasks.pipeline import run_pipeline
        async_result = run_pipeline.delay(inp.model_dump(mode="json"))
    except Exception as e:  # noqa: BLE001
        release_user_lock(user.id, inp.session_id)
        logger.exception(f"{log_prefix}.enqueue_failed", error=str(e))
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

    start_subscriber(
        context.application,
        session_id=inp.session_id,
        chat_id=chat_id,
        message_id=status_msg.message_id,
        on_terminal=make_on_terminal(context.application),
    )
    logger.info(
        f"{log_prefix}.enqueued",
        session_id=inp.session_id,
        task_id=async_result.id,
        user_id=user.id,
    )


@guarded
async def verstai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _dispatch_pptx_job(update, context, mode=Mode.VERSTAI, log_prefix="verstai")


@guarded
async def design(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _dispatch_pptx_job(update, context, mode=Mode.DESIGN, log_prefix="design")


@guarded
async def html(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _dispatch_pptx_job(update, context, mode=Mode.HTML, log_prefix="html")
