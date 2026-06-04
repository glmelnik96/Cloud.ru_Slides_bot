"""Whitelist gate: drop messages and callbacks from non-allowed Telegram users."""
from __future__ import annotations

from typing import Callable, Awaitable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.i18n.ru import START_NO_ACCESS

logger = structlog.get_logger(__name__)


def is_allowed(user_id: int) -> bool:
    return user_id in get_settings().telegram_whitelist


async def whitelist_guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    inner: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
) -> None:
    """Run `inner` only if the effective user is whitelisted.

    Designed to be wrapped around any handler at registration time.
    """
    user = update.effective_user
    if user is None or not is_allowed(user.id):
        if update.effective_message is not None:
            await update.effective_message.reply_text(START_NO_ACCESS)
        logger.info(
            "whitelist.rejected",
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
        )
        return
    await inner(update, context)


def guarded(handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]):
    """Decorator form for convenience: `@guarded` on a handler function."""

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await whitelist_guard(update, context, handler)

    wrapper.__name__ = handler.__name__
    return wrapper
