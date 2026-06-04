"""Role → (model, thinking-toggle, max_tokens) registry.

Single source of truth for the pipeline. Each LangGraph node imports its
RoleSpec from here and never hard-codes a model name.

Empirical findings — see <project>/memory/cloudru_fm_api.md.

Mapping rationale (M3, v0.9 batch):
- Only Kimi-K2.6 is multimodal on Cloud.ru FM → Brief (01) and Visual
  Verifier (10) MUST use it. Vision-grounding also fixes Kimi's
  text-only brief instability ("often invalid" at 3.7s).
- DeepSeek-V4-Pro is non-reasoning, ~0.7–3.8s on JSON → 02 Classifier
  and 04 Designer (terse lookup-table reasoning).
- GLM-5.1 thinking-OFF is the stable nested-JSON workhorse → 03
  Distributor, 05 Icons, 06 Infographic, 07 Copy Editor.
- GLM-5.1 thinking-ON gives harshest critic recall (score=10 vs
  DeepSeek 30) → kept for BRAND_GUARDIAN_CRITIC and AUTOFIX (used
  outside the v0.9 batch loop, in future autofix iterations).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    # v0.9 batch agents (M3)
    BRIEF_PARSER = "brief_parser"            # 01 — Kimi vision
    CLASSIFIER = "classifier"                # 02 — DeepSeek
    DISTRIBUTOR = "distributor"              # 03 — GLM OFF
    DESIGNER = "designer"                    # 04 — DeepSeek
    ICON_PICKER = "icon_picker"              # 05 — GLM OFF
    INFOGRAPHIC_MAKER = "infographic_maker"  # 06 — GLM OFF
    COPY_EDITOR = "copy_editor"              # 07 — GLM OFF
    VISUAL_VERIFIER = "visual_verifier"      # 10 — Kimi vision

    # Reserved for future autofix / critic loops (not used in M3 batch flow)
    BRAND_GUARDIAN_CRITIC = "brand_guardian_critic"
    AUTOFIX = "autofix"
    OUTLINE_BUILDER = "outline_builder"
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
    # ── v0.9 batch agents ──────────────────────────────────────────────
    Role.BRIEF_PARSER:
        # Kimi vision — reasoning ~7-9k chars (counted under completion_tokens
        # per cloudru_fm_api.md). Need room for both reasoning + Brief JSON
        # of up-to-20-slide deck. 3500 caused content truncation on 8+ slides.
        # 2026-06-04 live: 14-slide deck → reasoning ate entire 8000-token
        # budget, model never emitted content (empty content, both retries).
        # 12000 mirrors VISUAL_VERIFIER which handles 15-slide decks safely.
        RoleSpec(model="moonshotai/Kimi-K2.6", max_tokens=12000, requires_vision=True),
    Role.CLASSIFIER:
        # Per-deck DeckClassification with optional native blocks
        # (kpi/table/flow can be large). Empirically a 15-slide deck with
        # several natives hits ~3500 output tokens — 2500 truncated big.
        RoleSpec(model="deepseek-ai/DeepSeek-V4-Pro", max_tokens=4000),
    Role.DISTRIBUTOR:
        # Per-deck ContentAssignment, GLM OFF for nested-JSON stability.
        # 2500 truncated mid-string on a 15-slide deck (Unterminated string
        # at pos 9363 on 2026-06-04 live run). Russian Cyrillic content +
        # per-placeholder diff strings push output past 8KB on big decks.
        # Bump to 6000 — same envelope as INFOGRAPHIC_MAKER.
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=6000, extra_body=_GLM_THINKING_OFF),
    Role.DESIGNER:
        # LayoutPlan over the deck; DeepSeek terse table-lookup style.
        RoleSpec(model="deepseek-ai/DeepSeek-V4-Pro", max_tokens=2000),
    Role.ICON_PICKER:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=1500, extra_body=_GLM_THINKING_OFF),
    Role.INFOGRAPHIC_MAKER:
        # Shape lists with EMU coordinates can grow; 4000 truncated big-deck
        # output mid-shape. Prompt also nudges compact JSON (no whitespace).
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=6000, extra_body=_GLM_THINKING_OFF),
    Role.COPY_EDITOR:
        # 15-slide deck × per-slot diff strings → 2000 truncated big deck.
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=4000, extra_body=_GLM_THINKING_OFF),
    Role.VISUAL_VERIFIER:
        # Kimi vision always reasons (~5-9k chars), tokens counted under
        # completion_tokens. 5-dim rubric × 15 slides + ghost-deck narrative
        # = ~16k char output for big decks. 8000 truncated big near the end.
        RoleSpec(model="moonshotai/Kimi-K2.6", max_tokens=12000, requires_vision=True),

    # ── Reserved (autofix / future loops) ──────────────────────────────
    Role.BRAND_GUARDIAN_CRITIC:
        # Thinking ON intentionally — empirically yielded the harshest, most
        # accurate verdict on synthetic brand violations (score=10 vs 30).
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=2500),
    Role.AUTOFIX:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=2500),
    Role.OUTLINE_BUILDER:
        RoleSpec(model="zai-org/GLM-5.1", max_tokens=1200, extra_body=_GLM_THINKING_OFF),
    Role.PIXEL_JUDGE:
        RoleSpec(model="moonshotai/Kimi-K2.6", max_tokens=2000, requires_vision=True),
}
