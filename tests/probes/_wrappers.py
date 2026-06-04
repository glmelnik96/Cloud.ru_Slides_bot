"""Deck-level Pydantic wrappers for probe schema validation.

Several agents emit a `{"slides": [...]}` envelope around the per-slide
contract defined in ``schemas.slides``. The orchestrator declares the
same wrappers privately inside ``graph/nodes/agents.py``. We mirror them
here so probe tests don't depend on graph internals.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from schemas.slides import ContentAssignment, IconAssignments, InfographicSpec


class DeckContent(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[ContentAssignment] = Field(default_factory=list)


class DeckIcons(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[IconAssignments] = Field(default_factory=list)


class DeckInfographics(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[InfographicSpec] = Field(default_factory=list)
