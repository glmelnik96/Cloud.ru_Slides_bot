"""M1 acceptance: all 3 Cloud.ru FM models reachable through the role registry.

Run with:
    pytest -m slow tests/integration/test_cloudru_smoke.py -v
"""
from __future__ import annotations

import pytest

from llm.client import LLMCall, call_role
from llm.roles import Role


# Roles that exercise each of the 3 models with their production toggle.
_PROBED_ROLES: list[tuple[Role, str]] = [
    (Role.CLASSIFIER, "deepseek-ai/DeepSeek-V4-Pro"),
    (Role.DESIGNER, "zai-org/GLM-5.1"),
    (Role.VISUAL_VERIFIER, "moonshotai/Kimi-K2.6"),
]


@pytest.mark.slow
@pytest.mark.parametrize("role,expected_model", _PROBED_ROLES)
def test_role_reachable(role: Role, expected_model: str) -> None:
    """Each role's underlying model returns a non-empty response."""
    result = call_role(LLMCall(
        role=role,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
    ))
    assert result.model == expected_model
    # GLM/Kimi may pad with reasoning; we only require *some* assistant content.
    assert result.content, f"empty content for {role.value} ({result.model})"
    assert "pong" in result.content.lower()
