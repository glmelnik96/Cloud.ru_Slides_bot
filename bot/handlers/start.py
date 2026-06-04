"""/start handler — onboarding with mode selector inline keyboard."""
from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.i18n.ru import (
    MODE_BUTTON_AUDIT,
    MODE_BUTTON_BRIEF,
    MODE_BUTTON_VERSTAI,
    MODE_HOW_TO_AUDIT,
    MODE_HOW_TO_BRIEF,
    MODE_HOW_TO_VERSTAI,
    START_WELCOME,
)
from bot.middleware.whitelist import guarded

logger = structlog.get_logger(__name__)


def _mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(MODE_BUTTON_VERSTAI, callback_data="mode:verstai")],
            [InlineKeyboardButton(MODE_BUTTON_AUDIT, callback_data="mode:audit")],
            [InlineKeyboardButton(MODE_BUTTON_BRIEF, callback_data="mode:brief")],
        ]
    )


@guarded
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("start.invoked", user_id=user.id if user else None)
    await update.message.reply_text(
        START_WELCOME,
        reply_markup=_mode_keyboard(),
        parse_mode=ParseMode.HTML,
    )


_MODE_HOWTOS = {
    "mode:verstai": MODE_HOW_TO_VERSTAI,
    "mode:audit": MODE_HOW_TO_AUDIT,
    "mode:brief": MODE_HOW_TO_BRIEF,
}


@guarded
async def mode_picked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data not in _MODE_HOWTOS:
        return
    await query.answer()
    await query.message.reply_text(_MODE_HOWTOS[query.data], parse_mode=ParseMode.HTML)
    logger.info("mode.picked", user_id=update.effective_user.id, mode=query.data)
