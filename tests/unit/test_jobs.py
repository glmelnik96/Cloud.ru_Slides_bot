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


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    import bot.jobs as jobs
    monkeypatch.setattr(jobs, "sync_client", lambda db: fake)
    return fake


def test_claim_user_lock_first_call_wins(fake_redis):
    from bot.jobs import claim_user_lock
    assert claim_user_lock(42, "sess-a") is True
    assert claim_user_lock(42, "sess-b") is False


def test_release_user_lock_only_if_owner(fake_redis):
    from bot.jobs import claim_user_lock, get_active_session, release_user_lock
    assert claim_user_lock(42, "sess-a") is True
    # Wrong session_id must not release the lock.
    release_user_lock(42, "sess-other")
    assert get_active_session(42) == "sess-a"
    # Correct session_id releases it.
    release_user_lock(42, "sess-a")
    assert get_active_session(42) is None


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
