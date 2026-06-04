"""Bot-side job registry: session_id ↔ (task_id, chat_id, message_id).

Kept in Redis (DB.TG_STATE) so progress listeners surviving a bot restart
can still find the active task. Single-task-per-user lock also lives here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

from storage.redis_client import DB, sync_client

logger = structlog.get_logger(__name__)

# Hash key formats:
#   job:{session_id}       — job metadata (chat_id, msg_id, task_id, user_id, mode, started_at)
#   user_lock:{user_id}    — currently active session_id, or absent

_JOB_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days — matches session bundle TTL


def _job_key(session_id: str) -> str:
    return f"job:{session_id}"


def _lock_key(user_id: int) -> str:
    return f"user_lock:{user_id}"


def claim_user_lock(user_id: int, session_id: str) -> bool:
    """Atomically claim the single-session lock for a user.

    Returns True if the lock was acquired, False if the user already has an
    active job. Lock auto-expires after the job TTL.
    """
    r = sync_client(DB.TG_STATE)
    return bool(r.set(_lock_key(user_id), session_id, nx=True, ex=_JOB_TTL_SECONDS))


def get_active_session(user_id: int) -> str | None:
    return sync_client(DB.TG_STATE).get(_lock_key(user_id))


def release_user_lock(user_id: int, session_id: str) -> None:
    """Release the lock only if it still points at *this* session."""
    r = sync_client(DB.TG_STATE)
    current = r.get(_lock_key(user_id))
    if current == session_id:
        r.delete(_lock_key(user_id))


def save_job(*, session_id: str, user_id: int, chat_id: int,
             message_id: int, task_id: str, mode: str) -> None:
    r = sync_client(DB.TG_STATE)
    r.setex(
        _job_key(session_id),
        _JOB_TTL_SECONDS,
        json.dumps({
            "session_id": session_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "task_id": task_id,
            "mode": mode,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }),
    )


def load_job(session_id: str) -> dict | None:
    raw = sync_client(DB.TG_STATE).get(_job_key(session_id))
    return json.loads(raw) if raw else None


def update_job_task_id(session_id: str, new_task_id: str) -> None:
    job = load_job(session_id)
    if not job:
        return
    job["task_id"] = new_task_id
    sync_client(DB.TG_STATE).setex(_job_key(session_id), _JOB_TTL_SECONDS, json.dumps(job))
