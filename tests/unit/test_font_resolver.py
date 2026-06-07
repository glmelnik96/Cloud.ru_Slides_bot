"""font_resolver maps PPTX typeface names + bold to SB Sans Display OTF files."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "skill_assets", "scripts"))

import font_resolver  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_caches():
    font_resolver._fonts_dir.cache_clear()
    font_resolver.resolve.cache_clear()
    yield
    # Clear again so a monkeypatched-miss result never leaks into other modules.
    font_resolver._fonts_dir.cache_clear()
    font_resolver.resolve.cache_clear()


def test_resolves_regular_by_default():
    path = font_resolver.resolve("SB Sans Display")
    assert path is not None
    assert path.endswith("SBSansDisplay-Regular.otf")
    assert os.path.isfile(path)


def test_bold_flag_wins_over_family():
    path = font_resolver.resolve("SB Sans Display", True)
    assert path.endswith("SBSansDisplay-Bold.otf")


def test_semibold_from_family_name():
    path = font_resolver.resolve("SB Sans Display Semibold")
    assert path.endswith("SBSansDisplay-SemiBold.otf")


def test_unknown_family_falls_back_to_regular():
    path = font_resolver.resolve("Some Unknown Font")
    assert path.endswith("SBSansDisplay-Regular.otf")


def test_none_family_resolves_regular():
    path = font_resolver.resolve(None)
    assert path.endswith("SBSansDisplay-Regular.otf")


def test_missing_font_dir_returns_none(monkeypatch):
    monkeypatch.setattr(font_resolver, "_CANDIDATE_DIRS", ("/no/such/dir",))
    font_resolver._fonts_dir.cache_clear()
    font_resolver.resolve.cache_clear()
    assert font_resolver.resolve("SB Sans Display") is None
