"""Role → (model, thinking-toggle, max_tokens) registry.

Single source of truth for the pipeline. Each LangGraph node imports its
RoleSpec from here and never hard-codes a model name.

Empirical findings — see <project>/memory/cloudru_fm_api.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    BRIEF_PARSER = "brief_parser"
    CLASSIFIER = "classifier"
    OUTLINE_BUILDER = "outline_builder"
    COPY_EDITOR = "copy_editor"
    DESIGNER = "designer"
    DISTRIBUTOR = "distributor"
    BRAND_GUARDIAN_CRITIC = "brand_guardian_critic"
    AUTOFIX = "autofix"
    VISUAL_VERIFIER = "visual_verifier"
    PIXEL_JUDGE = "pixel_judge"


@dataclass(frozen=True)
class RoleSpec:
    model: str
    max_tokens: int
    temperature: float = 0.0
    # extra_body passes per-request kwargs to the underlying OpenAI SDK call.
    # Used to disable reasoning where supported.
    extra_body: dict[str, Any] = field(default_factory=dict)
    # Vision roles set this to True so the dispatcher can validate inputs.
    requires_vision: bool = False


# GLM-5.1 thinking-OFF: the only toggle that actually disables reasoning.
_GLM_THINKING_OFF = {"chat_template_kwargs": {"enable_thinking": False}}
# Kimi-K2.6 thinking-OFF: partial reduction, text-only. Ignored on vision.
_KIMI_THINKING_OFF = {"thinking": {"type": "disabled"}}


ROLES: dict[Role, RoleSpec] = {
    Role.BRIEF_PARSER:
        RoleSpec(model="deepseek-ai/DeepSeek-V4-Pro", max_tokens=400),
    Role.CLASSIFIER:
        RoleSpec(model="deepseek-ai/DeepSeek-V4-Pro", max_tokens=200),
    Role.OUTLINE_BUILDER:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=1200, extra_body=_GLM_THINKING_OFF),
    Role.COPY_EDITOR:
        RoleSpec(model="deepseek-ai/DeepSeek-V4-Pro", max_tokens=400),
    Role.DESIGNER:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=800, extra_body=_GLM_THINKING_OFF),
    Role.DISTRIBUTOR:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=1200, extra_body=_GLM_THINKING_OFF),
    Role.BRAND_GUARDIAN_CRITIC:
        # Thinking ON intentionally — empirically yielded the harshest, most
        # accurate verdict on synthetic brand violations (score=10 vs 30).
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=2500),
    Role.AUTOFIX:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=2500),
    Role.VISUAL_VERIFIER:
        # Kimi vision always reasons; allocate enough budget regardless of toggle.
        RoleSpec(model="moonshotai/Kimi-K2.6", max_tokens=3000, requires_vision=True),
    Role.PIXEL_JUDGE:
        RoleSpec(model="moonshotai/Kimi-K2.6", max_tokens=2000, requires_vision=True),
}
