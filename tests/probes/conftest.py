"""Pytest plumbing for WS-E LLM probes.

Probe tests hit the *live* Cloud.ru FM API. To keep CI fast and cheap,
they are double-gated:

1. Marker ``cloudru_probe`` is registered in pyproject.toml.
2. Tests are SKIPPED unless BOTH conditions hold:
   - ``--cloudru`` CLI flag is passed, AND
   - ``CLOUDRU_API_KEY`` environment variable is set.

The report fixture is *session-scoped* so the 8 agent × 3 size matrix
accumulates into a single ``tests/probes/_report.md`` written at session
teardown. Per-test rows are appended via ``record_probe()``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest
from dotenv import load_dotenv

from tests.probes._report import ProbeReport
from tests.probes.fixtures import SIZES, Size

# Load .env at import time so the skip-gate below sees CLOUDRU_API_KEY without
# the operator needing to `export` it. Mirrors bot.config.get_settings() which
# already reads .env via pydantic-settings.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--cloudru",
        action="store_true",
        default=False,
        help="Run cloudru_probe-marked tests against live Cloud.ru FM API.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip cloudru_probe tests unless --cloudru AND CLOUDRU_API_KEY set."""
    if config.getoption("--cloudru") and os.getenv("CLOUDRU_API_KEY"):
        return
    reason = (
        "needs --cloudru flag and CLOUDRU_API_KEY env var "
        "(live Cloud.ru FM call)"
    )
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "cloudru_probe" in item.keywords:
            item.add_marker(skip)


# ─── Shared fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(params=SIZES, ids=list(SIZES))
def size(request: pytest.FixtureRequest) -> Size:
    """Parametrize each probe test over small / medium / big decks."""
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def probe_report() -> Iterator[ProbeReport]:
    """Session-scoped report collector. Writes markdown at teardown."""
    out_path = Path(__file__).parent / "_report.md"
    report = ProbeReport()
    yield report
    report.write(out_path)
