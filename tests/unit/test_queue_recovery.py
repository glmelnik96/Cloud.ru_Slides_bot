"""Startup queue-recovery: a bot restart drops every in-memory progress
subscriber, so a job that held the global run-slot is orphaned (its on_terminal
never fires). Recovery re-queues that interrupted job at the TAIL, frees the
lock, and dispatches the head so the backlog drains (incident 2026-06-07).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return self.store.pop(key, None)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def lpop(self, key):
        lst = self.lists.get(key)
        if not lst:
            return None
        return lst.pop(0)

    def llen(self, key):
        return len(self.lists.get(key, []))


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    import bot.jobs as jobs
    monkeypatch.setattr(jobs, "sync_client", lambda db: fake)
    return fake


@pytest.fixture
def inputs_root(tmp_path, monkeypatch):
    import bot.queue_dispatch as qd
    monkeypatch.setattr(qd, "_INPUTS_ROOT", tmp_path)
    return tmp_path


def _seed_job_and_input(inputs_root, session_id="orphan"):
    from bot.jobs import save_job
    save_job(session_id=session_id, user_id=11, chat_id=22,
             message_id=33, task_id="t-old", mode="verstai")
    (inputs_root / f"{session_id}.pptx").write_bytes(b"PK\x03\x04")


def test_requeue_interrupted_appends_fresh_session_at_tail(fake_redis, inputs_root):
    from bot.jobs import enqueue_job, queue_length
    from bot.queue_dispatch import requeue_interrupted

    enqueue_job({"session_id": "waiting-1"})
    _seed_job_and_input(inputs_root, "orphan")

    new_id = requeue_interrupted("orphan")

    assert new_id is not None
    assert new_id != "orphan"  # fresh session, not the dead checkpoint
    assert queue_length() == 2
    # The interrupted job lands at the TAIL, behind what was already waiting.
    tail = json.loads(fake_redis.lists["global_job_queue"][-1])
    assert tail["session_id"] == new_id
    assert tail["message_id"] == 33  # original progress message preserved
    assert tail["user_id"] == 11
    # Reuses the already-downloaded input file (keyed by the OLD session id).
    inp = tail["input_json"]
    assert inp["input_s3_key"].endswith("orphan.pptx")
    assert inp["session_id"] == new_id


def test_requeue_interrupted_no_job_returns_none(fake_redis, inputs_root):
    from bot.queue_dispatch import requeue_interrupted
    assert requeue_interrupted("missing") is None


def test_requeue_interrupted_missing_input_returns_none(fake_redis, inputs_root):
    from bot.jobs import save_job
    from bot.queue_dispatch import requeue_interrupted
    # Job metadata exists but the input file was reaped → cannot reprocess.
    save_job(session_id="orphan", user_id=1, chat_id=2,
             message_id=3, task_id="t", mode="verstai")
    assert requeue_interrupted("orphan") is None


@pytest.mark.asyncio
async def test_recover_on_startup_requeues_orphan_releases_lock_dispatches(
    fake_redis, inputs_root, monkeypatch
):
    from bot.jobs import claim_global_lock, enqueue_job, get_active_session, queue_length
    import bot.queue_dispatch as qd

    # A restart left the lock held by "orphan" with two jobs waiting behind it.
    enqueue_job({"session_id": "waiting-1"})
    enqueue_job({"session_id": "waiting-2"})
    _seed_job_and_input(inputs_root, "orphan")
    assert claim_global_lock("orphan") is True

    dispatched = AsyncMock()
    monkeypatch.setattr(qd, "dispatch_next", dispatched)

    await qd.recover_queue_on_startup(AsyncMock())

    # Orphan lock freed so the slot can be claimed again.
    assert get_active_session() is None
    # Orphan re-queued at the tail → 3 waiting now.
    assert queue_length() == 3
    tail = json.loads(fake_redis.lists["global_job_queue"][-1])
    assert tail["message_id"] == 33  # the orphan's progress message
    # And the head gets dispatched to resume draining.
    dispatched.assert_awaited_once()


@pytest.mark.asyncio
async def test_recover_on_startup_noop_when_idle(fake_redis, inputs_root, monkeypatch):
    import bot.queue_dispatch as qd
    dispatched = AsyncMock()
    monkeypatch.setattr(qd, "dispatch_next", dispatched)
    # No lock, empty queue → nothing to do.
    await qd.recover_queue_on_startup(AsyncMock())
    dispatched.assert_not_awaited()
