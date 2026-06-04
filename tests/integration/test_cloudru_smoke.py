"""M1 acceptance: all 3 Cloud.ru FM models reachable through the role registry.

Run with:
    pytest -m slow tests/integration/test_cloudru_smoke.py -v

DESIGNER moved from GLM-5.1 to DeepSeek-V4-Pro in M3 (per
memory/cloudru_fm_api.md realignment). Kept GLM-5.1 probe via
DISTRIBUTOR which still uses thinking-OFF GLM.
"""
from __future__ import annotations

import pytest

from llm.client import LLMCall, call_role
from llm.roles import ROLES, Role


# Roles that exercise each of the 3 models with their production toggle.
_PROBED_ROLES: list[tuple[Role, str]] = [
    (Role.CLASSIFIER, "deepseek-ai/DeepSeek-V4-Pro"),
    (Role.DISTRIBUTOR, "zai-org/GLM-5.1"),
    (Role.VISUAL_VERIFIER, "moonshotai/Kimi-K2.6"),
]

# 1×1 transparent PNG used to satisfy the vision-gate when probing Kimi.
# Smallest valid PNG — Kimi tolerates it (returns text-only output).
_PIXEL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


@pytest.mark.slow
@pytest.mark.parametrize("role,expected_model", _PROBED_ROLES)
def test_role_reachable(role: Role, expected_model: str) -> None:
    """Each role's underlying model returns a non-empty response."""
    images = [_PIXEL_PNG_DATA_URL] if ROLES[role].requires_vision else []
    result = call_role(LLMCall(
        role=role,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        images=images,
    ))
    assert result.model == expected_model
    # GLM/Kimi may pad with reasoning; we only require *some* assistant content.
    assert result.content, f"empty content for {role.value} ({result.model})"
    assert "pong" in result.content.lower()
