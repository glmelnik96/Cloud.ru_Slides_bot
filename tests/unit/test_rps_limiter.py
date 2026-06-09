"""Tests for the Cloud.ru RPS limiter in llm/client.py.

TDD: these tests were written before the implementation.
"""
from __future__ import annotations

import os
import threading
import time

import pytest


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fresh_limiter(rps: float, monkeypatch, *, env_var: str = "CLOUDRU_MAX_RPS"):
    """Return a fresh acquire_rps_slot callable with the given RPS setting.

    We reload the module so the module-level state (_rps_lock, _next_allowed)
    is reset between tests.  Using monkeypatch ensures the env var is cleaned
    up automatically.
    """
    monkeypatch.setenv(env_var, str(rps))
    # Force re-import so cached env value is re-read.
    import importlib
    import llm.client as mod
    importlib.reload(mod)
    return mod.acquire_rps_slot


# ─── Part 1: roles max_tokens values ─────────────────────────────────────────

class TestRolesMaxTokens:
    def test_distributor_max_tokens(self):
        from llm.roles import ROLES, Role
        assert ROLES[Role.DISTRIBUTOR].max_tokens == 8000, (
            "DISTRIBUTOR max_tokens should be 8000 (pre-emptive headroom to avoid auto-bump)"
        )

    def test_copy_editor_max_tokens(self):
        from llm.roles import ROLES, Role
        assert ROLES[Role.COPY_EDITOR].max_tokens == 10000, (
            "COPY_EDITOR max_tokens should be 10000 (pre-emptive headroom to avoid auto-bump)"
        )

    def test_infographic_maker_max_tokens(self):
        from llm.roles import ROLES, Role
        assert ROLES[Role.INFOGRAPHIC_MAKER].max_tokens == 8000, (
            "INFOGRAPHIC_MAKER max_tokens should be 8000 (empirical max ~2813 tokens, 12000 was waste)"
        )

    def test_other_glm_roles_untouched(self):
        """Guard: roles we did NOT change must keep their previous values."""
        from llm.roles import ROLES, Role
        assert ROLES[Role.ICON_PICKER].max_tokens == 3000
        assert ROLES[Role.BRAND_GUARDIAN_CRITIC].max_tokens == 2500
        assert ROLES[Role.AUTOFIX].max_tokens == 2500
        assert ROLES[Role.OUTLINE_BUILDER].max_tokens == 1200
        assert ROLES[Role.SLIDE_COMPOSER].max_tokens == 6000


# ─── Part 2: RPS limiter primitive ───────────────────────────────────────────

class TestRpsLimiterBasic:
    def test_two_consecutive_spaced_correctly(self, monkeypatch):
        """With RPS=10 (interval=0.1s) two back-to-back calls are >= 0.1s apart."""
        acquire = _fresh_limiter(10.0, monkeypatch)
        t1 = time.monotonic()
        acquire()
        t2 = time.monotonic()
        acquire()
        t3 = time.monotonic()
        gap = t3 - t2   # second call should have waited
        # First call through should be near-instant; second >= interval.
        # We allow a small scheduling margin of 10ms below 100ms target.
        assert gap >= 0.090, f"Expected gap >= 0.090s, got {gap:.4f}s"

    def test_rps_zero_or_negative_no_delay(self, monkeypatch):
        """RPS <= 0 disables the limiter — no sleep should occur."""
        for rps_val in ("0", "-1", "0.0"):
            monkeypatch.setenv("CLOUDRU_MAX_RPS", rps_val)
            import importlib
            import llm.client as mod
            importlib.reload(mod)
            acquire = mod.acquire_rps_slot

            t0 = time.monotonic()
            for _ in range(5):
                acquire()
            elapsed = time.monotonic() - t0
            assert elapsed < 0.1, (
                f"RPS={rps_val}: 5 calls should be near-instant, took {elapsed:.4f}s"
            )

    def test_env_override_respected(self, monkeypatch):
        """CLOUDRU_MAX_RPS env var drives the rate."""
        # High RPS → very short interval → near-instant
        acquire = _fresh_limiter(1000.0, monkeypatch)
        t0 = time.monotonic()
        for _ in range(5):
            acquire()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1, (
            f"RPS=1000: 5 calls should be near-instant, took {elapsed:.4f}s"
        )


class TestRpsLimiterThreadSafety:
    def test_concurrent_threads_timestamps_spaced(self, monkeypatch):
        """With RPS=20 (interval=0.05s), 5 threads acquiring concurrently
        must produce timestamps strictly separated: total span >= 4 * 0.05s.
        """
        acquire = _fresh_limiter(20.0, monkeypatch)
        timestamps: list[float] = []
        lock = threading.Lock()

        def worker():
            acquire()
            with lock:
                timestamps.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        timestamps.sort()
        span = timestamps[-1] - timestamps[0]
        # 5 slots at 0.05s each → first can start at t=0, last at t≥0.20s
        assert span >= 4 * 0.045, (  # 10ms slack per slot
            f"Expected span >= 0.18s for 5 threads at RPS=20, got {span:.4f}s"
        )

    def test_no_double_slot_reservation(self, monkeypatch):
        """No two threads should be granted the same time slot (monotonic gaps)."""
        acquire = _fresh_limiter(50.0, monkeypatch)  # 0.02s interval
        slots: list[float] = []
        slot_lock = threading.Lock()

        def worker():
            acquire()
            # Record *after* the sleep — the time we actually started the call
            with slot_lock:
                slots.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        slots.sort()
        for i in range(1, len(slots)):
            gap = slots[i] - slots[i - 1]
            assert gap >= 0.012, (  # 8ms slack below 20ms interval
                f"Slots {i-1} and {i} are too close: gap={gap:.4f}s (expected >= 0.012s)"
            )
