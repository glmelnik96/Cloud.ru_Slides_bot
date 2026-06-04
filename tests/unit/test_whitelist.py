"""Whitelist parsing and gate decisions."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from bot.config import Settings


@pytest.fixture(autouse=True)
def _clear_singleton(monkeypatch):
    # bot.config caches Settings; clear it between tests.
    import bot.config
    monkeypatch.setattr(bot.config, "_settings", None)
    yield


def _settings(**overrides) -> Settings:
    base = {
        "CLOUDRU_API_KEY": "stub.stub",
        "TELEGRAM_BOT_TOKEN": "stub:stub",
        "TELEGRAM_WHITELIST": "",
    }
    base.update(overrides)
    with patch.dict(os.environ, base, clear=True):
        return Settings(_env_file=None)


def test_whitelist_empty_when_unset():
    s = _settings()
    assert s.telegram_whitelist == set()


def test_whitelist_parses_csv():
    s = _settings(TELEGRAM_WHITELIST="42, 100,  7")
    assert s.telegram_whitelist == {42, 100, 7}


def test_whitelist_ignores_garbage_whitespace():
    s = _settings(TELEGRAM_WHITELIST="  ,, 12,")
    assert s.telegram_whitelist == {12}


def test_api_key_strips_yaml_quotes():
    s = _settings(CLOUDRU_API_KEY=" 'abc.def' ")
    assert s.cloudru_api_key == "abc.def"
