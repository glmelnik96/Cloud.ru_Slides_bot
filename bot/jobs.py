"""Bot-side job registry: session_id ↔ (task_id, chat_id, message_id).

Kept in Redis (DB.TG_STATE) so progress listeners surviving a bot restart
can still find the active task. The per-user run-slot lock and the pending
job queue also live here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog

from storage.redis_client import DB, sync_client

logger = structlog.get_logger(__name__)

# Key formats:
#   job:{session_id}         — job metadata (chat_id, msg_id, task_id, user_id, mode, started_at)
#   user_job_lock:{user_id}  — session_id of the one job currently running for that user, or absent
#   global_job_lock          — legacy key (kept for backward compat during startup recovery)
#   global_job_queue         — LIST of JSON entries waiting for the lock to free

_JOB_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days — matches session bundle TTL

_LOCK_KEY = "global_job_lock"
_USER_LOCK_PREFIX = "user_job_lock:"
_QUEUE_KEY = "global_job_queue"
# Cap the pending queue so a flood of uploads can't grow it unbounded.
QUEUE_MAX = 10


def _job_key(session_id: str) -> str:
    return f"job:{session_id}"


def _user_lock_key(user_id: int) -> str:
    return f"{_USER_LOCK_PREFIX}{user_id}"


# ---------------------------------------------------------------------------
# Per-user lock API (current)
# ---------------------------------------------------------------------------

def claim_user_lock(user_id: int, session_id: str) -> bool:
    """Atomically claim the per-user run-slot.

    Returns True if the lock was acquired, False if this user already has a
    job in flight. Different users can each hold their own slot simultaneously.
    The lock auto-expires after the job TTL as a stuck-job safety net.
    """
    r = sync_client(DB.TG_STATE)
    return bool(r.set(_user_lock_key(user_id), session_id, nx=True, ex=_JOB_TTL_SECONDS))


def get_active_session_for_user(user_id: int) -> str | None:
    """session_id of the job currently holding *this user's* lock, or None."""
    return sync_client(DB.TG_STATE).get(_user_lock_key(user_id))


def release_user_lock(user_id: int, session_id: str) -> None:
    """Release the per-user lock only if it still points at *this* session."""
    r = sync_client(DB.TG_STATE)
    key = _user_lock_key(user_id)
    if r.get(key) == session_id:
        r.delete(key)


def get_all_active_user_sessions() -> list[tuple[int, str]]:
    """Return [(user_id, session_id), ...] for all held per-user locks.

    Used by startup recovery to find any orphaned per-user locks left over from
    a crash/restart. Scans for ``user_job_lock:*`` keys.
    """
    r = sync_client(DB.TG_STATE)
    result: list[tuple[int, str]] = []
    # ``keys()`` may not exist on every stub — guard gracefully.
    keys_fn = getattr(r, "keys", None)
    if keys_fn is None:
        return result
    for raw_key in keys_fn(f"{_USER_LOCK_PREFIX}*"):
        # raw_key may be bytes or str depending on the Redis client config.
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        suffix = key[len(_USER_LOCK_PREFIX):]
        try:
            uid = int(suffix)
        except ValueError:
            continue
        session_id = r.get(key)
        if session_id is not None:
            result.append((uid, session_id))
    return result


# ---------------------------------------------------------------------------
# Legacy global-lock API (kept for startup recovery of old-format lock keys)
# ---------------------------------------------------------------------------

def claim_global_lock(session_id: str) -> bool:
    """Atomically claim the single global run-slot.

    Returns True if the lock was acquired, False if another job already holds
    it. The lock auto-expires after the job TTL as a stuck-job safety net.
    """
    r = sync_client(DB.TG_STATE)
    return bool(r.set(_LOCK_KEY, session_id, nx=True, ex=_JOB_TTL_SECONDS))


def get_active_session() -> str | None:
    """session_id of the job currently holding the global lock, or None."""
    return sync_client(DB.TG_STATE).get(_LOCK_KEY)


def release_global_lock(session_id: str) -> None:
    """Release the lock only if it still points at *this* session."""
    r = sync_client(DB.TG_STATE)
    if r.get(_LOCK_KEY) == session_id:
        r.delete(_LOCK_KEY)


def enqueue_job(entry: dict) -> int:
    """Append a pending-job entry to the tail of the queue.

    Returns the entry's 1-based position in the queue, or 0 if the queue is
    already at QUEUE_MAX (caller should reject the submission).
    """
    r = sync_client(DB.TG_STATE)
    if r.llen(_QUEUE_KEY) >= QUEUE_MAX:
        return 0
    return int(r.rpush(_QUEUE_KEY, json.dumps(entry)))


def dequeue_job() -> dict | None:
    """Pop the oldest pending-job entry from the head of the queue."""
    raw = sync_client(DB.TG_STATE).lpop(_QUEUE_KEY)
    return json.loads(raw) if raw else None


def requeue_front(entry: dict) -> None:
    """Push an entry back to the head — used when a dispatch loses a lock race."""
    sync_client(DB.TG_STATE).lpush(_QUEUE_KEY, json.dumps(entry))


def queue_length() -> int:
    return int(sync_client(DB.TG_STATE).llen(_QUEUE_KEY))


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
