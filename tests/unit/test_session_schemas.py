"""Session contracts: SessionInput defaults, SessionState transitions, JSON roundtrip."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from schemas.session import Mode, ProgressEvent, SessionInput, SessionState, Stage


def test_session_input_defaults_session_id_and_created_at():
    inp = SessionInput(user_id=1, chat_id=2, progress_message_id=3, mode=Mode.VERSTAI)
    assert len(inp.session_id) == 16
    assert all(c in "0123456789abcdef" for c in inp.session_id)
    assert inp.created_at.tzinfo is timezone.utc
    assert inp.input_s3_key is None


def test_session_input_session_id_is_unique():
    a = SessionInput(user_id=1, chat_id=2, progress_message_id=3, mode=Mode.AUDIT)
    b = SessionInput(user_id=1, chat_id=2, progress_message_id=3, mode=Mode.AUDIT)
    assert a.session_id != b.session_id


def test_session_state_from_input_carries_identity():
    inp = SessionInput(
        user_id=42, chat_id=100, progress_message_id=7, mode=Mode.BRIEF,
        input_s3_key="s3://bucket/key.docx",
    )
    state = SessionState.from_input(inp)
    assert state.session_id == inp.session_id
    assert state.user_id == 42
    assert state.chat_id == 100
    assert state.progress_message_id == 7
    assert state.mode == "brief"
    assert state.input_s3_key == "s3://bucket/key.docx"
    assert state.stage == Stage.QUEUED.value
    assert state.progress_pct == 0
    assert state.autofix_iterations == 0


def test_session_state_forbids_extra_fields():
    with pytest.raises(Exception):
        SessionState(
            session_id="abc",
            user_id=1, chat_id=2, progress_message_id=3,
            mode="verstai", created_at_iso=datetime.now(timezone.utc).isoformat(),
            bogus_field="nope",
        )


def test_session_state_is_json_roundtrippable():
    """RedisSaver must be able to JSON-encode the state without datetime quirks."""
    inp = SessionInput(user_id=1, chat_id=2, progress_message_id=3, mode=Mode.VERSTAI)
    state = SessionState.from_input(inp)
    blob = state.model_dump(mode="json")
    rehydrated = SessionState.model_validate(json.loads(json.dumps(blob)))
    assert rehydrated == state


def test_progress_event_terminal_defaults_false():
    ev = ProgressEvent(session_id="x", stage=Stage.PARSING.value, progress_pct=10, detail="d")
    assert ev.terminal is False
    assert ev.error is None


def test_progress_event_terminal_with_error():
    ev = ProgressEvent(
        session_id="x", stage=Stage.FAILED.value, progress_pct=100,
        terminal=True, error="boom",
    )
    assert ev.terminal is True
    assert ev.error == "boom"
