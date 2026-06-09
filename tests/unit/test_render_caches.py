"""Tests for process-level render caches (perf item B3).

Covers:
  1. Template bytes cache in skill_assets/scripts/build_v9.py
  2. Icon-library scan cache in graph/nodes/agents.py
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_v9():
    """Import build_v9 module, reloading it so its module-level cache is fresh."""
    # build_v9 lives in skill_assets/scripts and does sys.path.insert on load.
    scripts_dir = Path(__file__).parents[2] / "skill_assets" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import importlib
    if "build_v9" in sys.modules:
        del sys.modules["build_v9"]
    import build_v9  # noqa: PLC0415
    return build_v9


# ---------------------------------------------------------------------------
# 1. Template bytes cache
# ---------------------------------------------------------------------------

class TestTemplateBytesCache:
    """_read_bytes_cached(path) in build_v9 must read once and cache by
    (resolved_path, mtime, size); invalidate when mtime or size changes.
    """

    def test_second_call_returns_same_bytes_object(self, tmp_path):
        """Cache hit: same bytes object (identity) on second call."""
        m = _build_v9()
        tpl = tmp_path / "template.pptx"
        tpl.write_bytes(b"FAKE_PPTX_CONTENT_v1")

        b1 = m._read_bytes_cached(str(tpl))
        b2 = m._read_bytes_cached(str(tpl))
        assert b1 is b2, "Expected same bytes object on cache hit"

    def test_file_read_called_only_once(self, tmp_path):
        """File must be read exactly once for two calls with no change."""
        m = _build_v9()
        tpl = tmp_path / "template.pptx"
        content = b"FAKE_PPTX_CONTENT_v2"
        tpl.write_bytes(content)

        read_count = [0]
        original_read_bytes = Path.read_bytes

        def counting_read_bytes(self):
            if self == tpl.resolve():
                read_count[0] += 1
            return original_read_bytes(self)

        with patch.object(Path, "read_bytes", counting_read_bytes):
            m._TEMPLATE_BYTES_CACHE.clear()  # ensure clean state
            m._read_bytes_cached(str(tpl))
            m._read_bytes_cached(str(tpl))

        assert read_count[0] == 1, f"Expected 1 read, got {read_count[0]}"

    def test_cache_invalidates_on_content_change(self, tmp_path):
        """Write new content → new bytes returned (cache miss)."""
        m = _build_v9()
        tpl = tmp_path / "template.pptx"
        tpl.write_bytes(b"VERSION_ONE_____")

        b1 = m._read_bytes_cached(str(tpl))

        # Overwrite with different content (changes mtime and size).
        time.sleep(0.01)  # ensure mtime differs on fast filesystems
        tpl.write_bytes(b"VERSION_TWO_LONGER")

        b2 = m._read_bytes_cached(str(tpl))
        assert b1 != b2, "Expected new bytes after file change"
        assert b2 == b"VERSION_TWO_LONGER"

    def test_cache_invalidates_on_size_change(self, tmp_path):
        """A file written with different size must miss the cache."""
        m = _build_v9()
        tpl = tmp_path / "template.pptx"
        tpl.write_bytes(b"AAAA")
        m._read_bytes_cached(str(tpl))

        tpl.write_bytes(b"AAAABBBB")  # same or later mtime, bigger size
        b2 = m._read_bytes_cached(str(tpl))
        assert b2 == b"AAAABBBB"

    def test_bytes_are_independent_copies_not_modified(self, tmp_path):
        """Modifying the returned bytes (via bytearray) should not corrupt cache."""
        m = _build_v9()
        tpl = tmp_path / "template.pptx"
        tpl.write_bytes(b"IMMUTABLE_CONTENT")

        b1 = m._read_bytes_cached(str(tpl))
        b2 = m._read_bytes_cached(str(tpl))
        # bytes are immutable in Python — this just confirms they are bytes
        assert isinstance(b1, bytes)
        assert isinstance(b2, bytes)


# ---------------------------------------------------------------------------
# 2. Icon library scan cache
# ---------------------------------------------------------------------------

class TestIconScanCache:
    """icons_node uses _get_icon_library(icons_dir) which should glob only once
    per icons-directory mtime (or just once for a static dir).
    """

    def _import_agents(self):
        """Return graph.nodes.agents module with fresh cache state."""
        import graph.nodes.agents as ag
        # Clear module-level icons cache between tests.
        ag._ICONS_CACHE.clear()
        return ag

    def test_returns_sorted_list(self, tmp_path):
        """Sorted list of icon paths returned correctly."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        (icons_dir / "zoom.svg").write_text("")
        (icons_dir / "alpha.svg").write_text("")
        (icons_dir / "middle.svg").write_text("")

        result = ag._get_icon_library(icons_dir)
        assert result == ["icons/alpha.svg", "icons/middle.svg", "icons/zoom.svg"]

    def test_non_svg_files_excluded(self, tmp_path):
        """Only .svg files are included."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        (icons_dir / "good.svg").write_text("")
        (icons_dir / "bad.png").write_text("")
        (icons_dir / "also_bad.txt").write_text("")

        result = ag._get_icon_library(icons_dir)
        assert result == ["icons/good.svg"]

    def test_empty_dir_returns_empty_list(self, tmp_path):
        """Empty icons dir → empty list."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()

        result = ag._get_icon_library(icons_dir)
        assert result == []

    def test_missing_dir_returns_empty_list(self, tmp_path):
        """Non-existent icons dir → empty list (no exception)."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons_nonexistent"

        result = ag._get_icon_library(icons_dir)
        assert result == []

    def test_glob_called_only_once_for_same_dir(self, tmp_path):
        """Two calls with same dir: glob should fire only once."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        (icons_dir / "a.svg").write_text("")
        (icons_dir / "b.svg").write_text("")

        glob_count = [0]
        orig_glob = Path.glob

        def counting_glob(self, pattern):
            if self == icons_dir and pattern == "*.svg":
                glob_count[0] += 1
            return orig_glob(self, pattern)

        with patch.object(Path, "glob", counting_glob):
            ag._ICONS_CACHE.clear()
            ag._get_icon_library(icons_dir)
            ag._get_icon_library(icons_dir)

        assert glob_count[0] == 1, f"Expected 1 glob call, got {glob_count[0]}"

    def test_second_call_returns_same_list_object(self, tmp_path):
        """Cache hit: same list object (identity) returned on second call."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        (icons_dir / "x.svg").write_text("")

        r1 = ag._get_icon_library(icons_dir)
        r2 = ag._get_icon_library(icons_dir)
        assert r1 is r2, "Expected same list object on cache hit"

    def test_thread_safety(self, tmp_path):
        """Concurrent calls must not raise or produce garbage."""
        ag = self._import_agents()
        icons_dir = tmp_path / "icons"
        icons_dir.mkdir()
        for i in range(5):
            (icons_dir / f"icon{i}.svg").write_text("")

        results = []
        errors = []

        def worker():
            try:
                r = ag._get_icon_library(icons_dir)
                results.append(r)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert all(len(r) == 5 for r in results)
