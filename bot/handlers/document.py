"""Document-with-caption router.

PTB's CommandHandler matches commands only in `message.text`, not in
`message.caption`. So a file uploaded with caption `/verstai` is invisible
to the regular command handlers. This module catches every document upload
and, if the caption starts with `/verstai|/audit|/brief`, dispatches to the
matching handler.
"""
from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.placeholders import audit, brief
from bot.handlers.verstai import verstai
from bot.middleware.whitelist import guarded

logger = structlog.get_logger(__name__)

_DISPATCH = {
    "verstai": verstai,
    "audit": audit,
    "brief": brief,
}


@guarded
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if msg is None or msg.document is None:
        return
    caption = (msg.caption or "").strip()
    if not caption.startswith("/"):
        # Bare upload — let the user follow up with a reply-command.
        return
    head = caption.split(maxsplit=1)[0]
    cmd = head[1:].split("@", 1)[0].lower()
    handler = _DISPATCH.get(cmd)
    if handler is None:
        return
    # Mirror CommandHandler semantics so downstream code can read context.args.
    context.args = caption.split()[1:]
    logger.info(
        "document.routed",
        user_id=update.effective_user.id if update.effective_user else None,
        command=cmd,
        file_name=msg.document.file_name,
    )
    await handler(update, context)
