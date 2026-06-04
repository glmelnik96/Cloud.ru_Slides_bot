"""Stubs for /audit, /brief — implemented in later milestones (M5)."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.i18n.ru import NOT_IMPLEMENTED_YET
from bot.middleware.whitelist import guarded


@guarded
async def audit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(NOT_IMPLEMENTED_YET)


@guarded
async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(NOT_IMPLEMENTED_YET)
