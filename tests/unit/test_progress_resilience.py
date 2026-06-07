"""Progress-subscriber resilience: a transient Telegram edit failure must never
propagate out of the subscriber. The subscriber owns lock-release + queue
advance + result delivery on the terminal event, so if a cosmetic progress edit
raises (TimedOut/NetworkError, or a stale-message BadRequest) and that bubbles
up, the whole pending queue is stranded (incident 2026-06-07).
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError, TimedOut

from bot.handlers.progress import _edit


def _app_raising(exc: Exception):
    app = AsyncMock()
    app.bot.edit_message_text = AsyncMock(side_effect=exc)
    return app


@pytest.mark.asyncio
async def test_edit_swallows_timed_out():
    app = _app_raising(TimedOut())
    # Must not raise — a cosmetic edit timeout cannot be allowed to kill the
    # subscriber and strand the queue.
    await _edit(app, chat_id=1, message_id=2, text="x", keyboard=None)


@pytest.mark.asyncio
async def test_edit_swallows_network_error():
    app = _app_raising(NetworkError("boom"))
    await _edit(app, chat_id=1, message_id=2, text="x", keyboard=None)


@pytest.mark.asyncio
async def test_edit_swallows_not_modified_badrequest():
    app = _app_raising(BadRequest("Message is not modified"))
    await _edit(app, chat_id=1, message_id=2, text="x", keyboard=None)


@pytest.mark.asyncio
async def test_edit_swallows_stale_message_badrequest():
    # User deleted the progress message → "message to edit not found". This must
    # also be non-fatal so the terminal path still delivers the result.
    app = _app_raising(BadRequest("Message to edit not found"))
    await _edit(app, chat_id=1, message_id=2, text="x", keyboard=None)
