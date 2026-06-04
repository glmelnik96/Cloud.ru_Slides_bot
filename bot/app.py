"""Entry point: build PTB Application, register handlers, run polling.

M1 scope: /start with mode selector + whitelist guard + placeholders for
/verstai, /audit, /brief. Real pipeline wiring lands in M2+.
"""
from __future__ import annotations

import structlog
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import get_settings
from bot.handlers.cancel import cancel_cmd, cancel_pressed
from bot.handlers.document import on_document
from bot.handlers.placeholders import audit, brief
from bot.handlers.resume import resume
from bot.handlers.start import mode_picked, start
from bot.handlers.verstai import verstai
from bot.logging_setup import configure_logging

logger = structlog.get_logger(__name__)


def build_app() -> Application:
    settings = get_settings()
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(mode_picked, pattern=r"^mode:"))
    app.add_handler(CommandHandler("verstai", verstai))
    app.add_handler(CommandHandler("audit", audit))
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(cancel_pressed, pattern=r"^cancel:"))
    # Captions on documents: route /verstai|/audit|/brief from the caption.
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    return app


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "bot.starting",
        whitelist_size=len(settings.telegram_whitelist),
        cloudru_base_url=settings.cloudru_base_url,
        max_concurrent_decks=settings.max_concurrent_decks,
    )
    if not settings.telegram_whitelist:
        logger.warning("bot.whitelist_empty — nobody will be allowed in")
    app = build_app()
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
