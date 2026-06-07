"""Async progress subscriber: Redis pub/sub → editMessageText with debouncing.

Per session, we spawn one asyncio Task. It subscribes to `progress:{id}`,
debounces edits (3 sec by default), strips the cancel keyboard on terminal
events, and exits cleanly.

`telegram.error.BadRequest` for "message is not modified" is swallowed —
Telegram raises it when the rendered text didn't actually change.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Awaitable, Callable

import structlog
from pydantic import ValidationError
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application

from bot.i18n.progress import format_progress, format_terminal
from schemas.session import ProgressEvent
from storage.redis_client import DB, async_client
from worker.progress import channel_name

logger = structlog.get_logger(__name__)

_DEBOUNCE_SECONDS = 3.0
# Per-session subscriber tasks so we can cancel them on shutdown or terminal events.
_active_subscribers: dict[str, asyncio.Task] = {}


def cancel_keyboard(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚫 Отменить", callback_data=f"cancel:{session_id}")]]
    )


async def _edit(app: Application, *, chat_id: int, message_id: int,
                text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Edit the progress message, best-effort.

    A progress edit is purely cosmetic, but the subscriber that calls it owns
    lock-release + queue advance + result delivery on the terminal event. So NO
    Telegram error may propagate out of here: a transient ``TimedOut`` /
    ``NetworkError`` on a mid-run edit, or a ``BadRequest`` because the user
    deleted the status message, must not kill the subscriber and strand the
    whole pending queue (incident 2026-06-07). All failures are swallowed and
    logged; "not modified" is the expected debounce no-op and stays quiet.
    """
    try:
        await app.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        logger.warning("progress.edit_failed", error=str(e), chat_id=chat_id)
    except TelegramError as e:
        # Any other Telegram-side failure (TimedOut, NetworkError, RetryAfter,
        # Forbidden…) is non-fatal for a cosmetic edit — log and carry on.
        logger.warning("progress.edit_failed", error=str(e), chat_id=chat_id)


async def subscribe(app: Application, *, session_id: str, chat_id: int,
                    message_id: int,
                    on_terminal: Callable[[ProgressEvent], Awaitable[None]] | None = None
                    ) -> None:
    """Subscribe to one session's progress channel. Returns when the channel
    emits a terminal event or the task is cancelled externally.
    """
    r = async_client(DB.PUBSUB)
    pubsub = r.pubsub()
    await pubsub.subscribe(channel_name(session_id))
    log = logger.bind(session_id=session_id)
    log.info("progress.subscribed")

    last_edit_at = 0.0
    pending: ProgressEvent | None = None

    async def flush() -> None:
        nonlocal last_edit_at, pending
        if pending is None:
            return
        text = format_progress(pending.stage, pending.progress_pct, pending.detail)
        await _edit(app, chat_id=chat_id, message_id=message_id,
                    text=text, keyboard=cancel_keyboard(session_id))
        last_edit_at = time.monotonic()
        pending = None

    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            try:
                event = ProgressEvent.model_validate(json.loads(msg["data"]))
            except (json.JSONDecodeError, ValidationError) as e:
                log.warning("progress.bad_event", error=str(e))
                continue

            if event.terminal:
                # Always flush terminal immediately, drop the keyboard.
                pending = None
                text = format_terminal(event.stage, event.error)
                await _edit(app, chat_id=chat_id, message_id=message_id,
                            text=text, keyboard=None)
                # On DONE, ship the built .pptx back to the user. Best-effort:
                # any Telegram or filesystem error is logged but does not break
                # the subscriber lifecycle.
                if event.stage == "done" and event.result_path:
                    try:
                        p = Path(event.result_path)
                        with p.open("rb") as f:
                            await app.bot.send_document(
                                chat_id=chat_id,
                                document=f,
                                filename=p.name,
                            )
                    except (OSError, TelegramError) as e:
                        log.warning("progress.send_document_failed",
                                    error=str(e), path=event.result_path)
                if on_terminal is not None:
                    with contextlib.suppress(Exception):
                        await on_terminal(event)
                log.info("progress.terminal", stage=event.stage)
                return

            pending = event
            now = time.monotonic()
            if now - last_edit_at >= _DEBOUNCE_SECONDS:
                await flush()
            else:
                # Schedule a delayed flush so the last update still lands.
                await asyncio.sleep(_DEBOUNCE_SECONDS - (now - last_edit_at))
                await flush()
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel_name(session_id))
            await pubsub.close()
            await r.close()


def start_subscriber(app: Application, *, session_id: str, chat_id: int,
                     message_id: int,
                     on_terminal: Callable[[ProgressEvent], Awaitable[None]] | None = None
                     ) -> asyncio.Task:
    """Fire-and-forget subscriber. Tracks the task so we can cancel/stop it."""
    if session_id in _active_subscribers and not _active_subscribers[session_id].done():
        logger.warning("progress.subscriber_already_running", session_id=session_id)
        return _active_subscribers[session_id]
    task = asyncio.create_task(
        subscribe(app, session_id=session_id, chat_id=chat_id,
                  message_id=message_id, on_terminal=on_terminal),
        name=f"progress-{session_id}",
    )

    def _cleanup(_: asyncio.Task) -> None:
        _active_subscribers.pop(session_id, None)

    task.add_done_callback(_cleanup)
    _active_subscribers[session_id] = task
    return task


def stop_subscriber(session_id: str) -> None:
    task = _active_subscribers.get(session_id)
    if task is not None and not task.done():
        task.cancel()
