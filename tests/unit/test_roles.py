"""Role registry sanity — guards against accidental mis-assignment."""
from __future__ import annotations

from llm.roles import ROLES, Role


def test_every_role_has_spec():
    for role in Role:
        assert role in ROLES, f"missing RoleSpec for {role.value}"


def test_vision_roles_use_kimi():
    for role, spec in ROLES.items():
        if spec.requires_vision:
            assert spec.model == "moonshotai/Kimi-K2.6", (
                f"{role.value} is vision but assigned {spec.model}"
            )


def test_glm_thinking_off_uses_chat_template_kwargs():
    """The only toggle that actually disables GLM-5.1 reasoning is chat_template_kwargs.

    See memory/cloudru_fm_api.md for the empirical verification.
    """
    for role, spec in ROLES.items():
        if spec.model == "zai-org/GLM-5.1" and spec.extra_body:
            assert "chat_template_kwargs" in spec.extra_body, (
                f"{role.value}: GLM with extra_body must use chat_template_kwargs.enable_thinking"
            )


def test_critic_and_autofix_keep_thinking_on():
    """Brand critic and autofix benefit from CoT — must NOT carry a thinking-off toggle."""
    for role in (Role.BRAND_GUARDIAN_CRITIC, Role.AUTOFIX):
        spec = ROLES[role]
        assert not spec.extra_body, (
            f"{role.value} must keep thinking ON (no extra_body), got {spec.extra_body}"
        )


def test_kimi_text_roles_use_thinking_disabled_toggle():
    # No Kimi text roles in current registry; if added, they should use the partial toggle.
    for role, spec in ROLES.items():
        if spec.model == "moonshotai/Kimi-K2.6" and not spec.requires_vision:
            assert spec.extra_body.get("thinking", {}).get("type") == "disabled"
