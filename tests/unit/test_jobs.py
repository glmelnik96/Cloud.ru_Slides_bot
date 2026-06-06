"""Session/user-lock registry — uses an in-memory fake Redis stub.

Avoids the fakeredis dependency: we only need GET/SET/SETEX/DELETE semantics.
"""
from __future__ import annotations

import json
from unittest.mock import patch

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


def test_claim_global_lock_first_call_wins(fake_redis):
    from bot.jobs import claim_global_lock
    # One global run-slot: the first job wins, any other is rejected until free.
    assert claim_global_lock("sess-a") is True
    assert claim_global_lock("sess-b") is False


def test_release_global_lock_only_if_owner(fake_redis):
    from bot.jobs import claim_global_lock, get_active_session, release_global_lock
    assert claim_global_lock("sess-a") is True
    # Wrong session_id must not release the lock.
    release_global_lock("sess-other")
    assert get_active_session() == "sess-a"
    # Correct session_id releases it; a queued job can then claim.
    release_global_lock("sess-a")
    assert get_active_session() is None
    assert claim_global_lock("sess-b") is True


def test_enqueue_returns_position_and_dequeue_is_fifo(fake_redis):
    from bot.jobs import dequeue_job, enqueue_job
    assert enqueue_job({"session_id": "s1"}) == 1
    assert enqueue_job({"session_id": "s2"}) == 2
    assert enqueue_job({"session_id": "s3"}) == 3
    # FIFO order out.
    assert dequeue_job()["session_id"] == "s1"
    assert dequeue_job()["session_id"] == "s2"
    assert dequeue_job()["session_id"] == "s3"
    assert dequeue_job() is None


def test_enqueue_rejects_when_full(fake_redis):
    from bot.jobs import QUEUE_MAX, enqueue_job, queue_length
    for i in range(QUEUE_MAX):
        assert enqueue_job({"session_id": f"s{i}"}) == i + 1
    assert queue_length() == QUEUE_MAX
    # Queue full → 0 (caller rejects the submission).
    assert enqueue_job({"session_id": "overflow"}) == 0
    assert queue_length() == QUEUE_MAX


def test_requeue_front_is_lifo_head(fake_redis):
    from bot.jobs import dequeue_job, enqueue_job, requeue_front
    enqueue_job({"session_id": "tail"})
    requeue_front({"session_id": "head"})
    # requeue_front lands at the head — dispatched before the older tail entry.
    assert dequeue_job()["session_id"] == "head"
    assert dequeue_job()["session_id"] == "tail"


def test_save_and_load_job_roundtrip(fake_redis):
    from bot.jobs import load_job, save_job
    save_job(
        session_id="s1", user_id=1, chat_id=2,
        message_id=3, task_id="celery-task-id", mode="verstai",
    )
    job = load_job("s1")
    assert job is not None
    assert job["session_id"] == "s1"
    assert job["user_id"] == 1
    assert job["task_id"] == "celery-task-id"
    assert job["mode"] == "verstai"
    assert "started_at" in job


def test_load_job_missing_returns_none(fake_redis):
    from bot.jobs import load_job
    assert load_job("does-not-exist") is None


def test_update_job_task_id_replaces_task(fake_redis):
    from bot.jobs import load_job, save_job, update_job_task_id
    save_job(
        session_id="s1", user_id=1, chat_id=2,
        message_id=3, task_id="task-old", mode="verstai",
    )
    update_job_task_id("s1", "task-new")
    assert load_job("s1")["task_id"] == "task-new"


def test_update_job_task_id_noop_for_missing_session(fake_redis):
    from bot.jobs import update_job_task_id
    # Should not raise.
    update_job_task_id("ghost", "task-x")
