"""Donor-slot-map helper — loads ``skill_assets/brand/donor-slot-map.yaml``
and exposes lookup helpers for the orchestration nodes.

``distribute_node`` needs per-layout slot capacities so GLM can fit copy
to safe_max_chars; ``assemble_plan_node`` needs a ph_idx → ph_name map
so PlanSlide.slots can use the canonical slot names ``build_v9`` keys on.

The YAML file is the single source of truth; we cache it on the first
call (worker process) and re-parse only on explicit ``reload()``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from worker import skill_bridge


def _map_path() -> Path:
    return Path(skill_bridge.DONOR_SLOT_MAP)


# YAML semantic slot names → canonical OOXML PlaceholderType enum.
# Kept here (not imported from schemas/) to avoid a circular import: schemas
# is at the bottom of the dependency graph and graph.donor_map is one of
# its consumers. The two tables MUST stay in sync — see PlaceholderType in
# schemas/slides.py. _normalize_ph_type there is a defensive fallback for
# anything that slips past this translation.
_OOXML_BY_SLOT_NAME: dict[str, str] = {
    "title": "TITLE",
    "center_title": "CENTER_TITLE",
    "subtitle": "SUBTITLE",
    "body": "BODY",
    "content": "CONTENT",
    "picture": "PICTURE",
    "image": "PICTURE",
    "logo": "PICTURE",
}


def _slot_name_to_ooxml(slot_name: str) -> str:
    """Translate a YAML semantic slot key (e.g. ``col1_body``) into the
    canonical OOXML PlaceholderType enum (e.g. ``BODY``). Falls back to
    substring detection for multi-column variants (``col1_body``,
    ``body_left`` → BODY); anything unrecognised becomes ``OTHER``.
    """
    s = (slot_name or "").lower().strip()
    if s in _OOXML_BY_SLOT_NAME:
        return _OOXML_BY_SLOT_NAME[s]
    if "title" in s:
        return "TITLE"
    if "body" in s:
        return "BODY"
    if "content" in s:
        return "CONTENT"
    if "picture" in s or "image" in s or "logo" in s:
        return "PICTURE"
    return "OTHER"


@lru_cache(maxsize=1)
def _load_raw() -> dict[str, Any]:
    """Parse donor-slot-map.yaml and return the whole document.

    Donor IDs in the YAML are YAML integer keys; PyYAML returns them as
    ``int``. We keep that type so callers can lookup with the same
    ``layout_idx`` value that flows through LayoutPlan.
    """
    path = _map_path()
    if not path.is_file():
        raise FileNotFoundError(f"donor-slot-map missing: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _load() -> dict[int, dict[str, Any]]:
    raw = _load_raw()
    donors = raw.get("donors") or {}
    return {int(k): v for k, v in donors.items() if v}


def reload() -> None:
    """Drop the cached map. Use in tests when the YAML changes on disk."""
    _load.cache_clear()
    _load_raw.cache_clear()


def valid_donor_ids() -> set[int]:
    """Set of donor indices that exist in donor-slot-map.yaml.

    Designer picks outside this set silently degrade to template default
    text (see stack_gotchas #10 — first live run had donors 1 and 9 chosen,
    which are template-internal meta-slides, not real donors). Use this
    set to reject hallucinated picks before they reach build_v9.
    """
    return set(_load().keys())


def category_equivalence() -> dict[str, list[int]]:
    """Return ``{yaml_category: [donor_idx, ...]}`` from the YAML.

    Empty lists are dropped (e.g. ``team`` has no usable donors in the
    current template — those are all photo-PNGs).
    """
    raw = _load_raw()
    out: dict[str, list[int]] = {}
    for cat, lst in (raw.get("category_equivalence") or {}).items():
        ids = [int(x) for x in (lst or []) if isinstance(x, int)]
        # Defensive: keep only donors that are actually mapped.
        ids = [i for i in ids if i in valid_donor_ids()]
        if ids:
            out[str(cat)] = ids
    return out


def tone_groups() -> dict[str, list[int]]:
    raw = _load_raw()
    out: dict[str, list[int]] = {}
    for grp, lst in (raw.get("tone_groups") or {}).items():
        ids = [int(x) for x in (lst or []) if isinstance(x, int)]
        ids = [i for i in ids if i in valid_donor_ids()]
        if ids:
            out[str(grp)] = ids
    return out


# Bridge between SlideCategory (schemas/slides.py) + subcategory_hint (free text
# from classifier) and the canonical categories in donor-slot-map.yaml. Keep the
# values strictly in sync with `category_equivalence` keys in the YAML.
_CATEGORY_BRIDGE: dict[str, list[str]] = {
    "title":       ["title_open", "title_dark"],
    "divider":     ["divider"],
    "text":        ["content_text"],
    "multicolumn": ["content_2col", "content_3col", "content_4block", "content_text"],
    "image":       ["image_grid", "image_main", "screenshot"],
    "team":        ["team"],
    "timeline":    ["timeline"],
    "table":       ["table"],
    "callout":     ["callout"],
    "logo":        ["logo_finale"],
    # pattern_bg/tech/other have no first-class mapping — fall back to content_text.
    "pattern_bg":  ["content_text"],
    "tech":        ["content_text"],
    "other":       ["content_text"],
}

# Subcategory hints from the classifier ("2col", "3col", "4subtitles", "6blocks",
# "8blocks", "kpi3") narrow multicolumn picks. The classifier emits these as
# free-form strings; we substring-match to stay resilient.
_SUBCAT_OVERRIDES: list[tuple[str, str]] = [
    ("2col",       "content_2col"),
    ("3col",       "content_3col"),
    ("4block",     "content_4block"),  # matches "4blocks" and "4block"
    ("4subtitle",  "content_4block"),
    ("6block",     "content_6subtitles"),  # only present if added to YAML
    ("8block",     "content_8subtitles"),
    ("kpi",        "kpi"),
]


def default_donor_for_category(
    category: str,
    subcategory_hint: str | None = None,
    dark: bool = False,
) -> int | None:
    """Pick a sensible donor index for a (category, subcategory_hint) pair.

    Returns the first valid donor index from the relevant
    ``category_equivalence`` bucket, or ``None`` if nothing in the YAML
    fits — caller should keep the LLM's pick or fall back to a safe text
    donor of its own choosing.

    Honours ``dark`` for title category (prefers ``title_dark`` first).
    """
    eq = category_equivalence()
    sub = (subcategory_hint or "").lower()
    # Subcategory hint wins if it matches a known multicolumn variant.
    for needle, yaml_key in _SUBCAT_OVERRIDES:
        if needle in sub and eq.get(yaml_key):
            return eq[yaml_key][0]
    buckets = list(_CATEGORY_BRIDGE.get(category, []))
    if category == "title" and dark:
        # Promote dark variant if requested.
        buckets = [b for b in buckets if b == "title_dark"] + \
                  [b for b in buckets if b != "title_dark"]
    for b in buckets:
        ids = eq.get(b)
        if ids:
            return ids[0]
    return None


def donor_summary() -> list[dict[str, Any]]:
    """Compact per-donor record for the Layout Designer prompt.

    Returns a list of ``{idx, category, description, use_when, max_chars}``
    sorted by idx. Drives the dynamically-generated DONOR_TABLE in
    ``llm/prompts/agent_04_layout_designer.py`` — keep this small (one
    line per donor) so the prompt stays within context budget.
    """
    out: list[dict[str, Any]] = []
    for idx, donor in sorted(_load().items()):
        slots = donor.get("slots") or {}
        # Find the longest text slot's max_chars as a rough capacity hint.
        max_chars = 0
        for slot in slots.values():
            if isinstance(slot, dict):
                v = slot.get("safe_max_chars") or slot.get("max_chars") or 0
                if isinstance(v, int) and v > max_chars:
                    max_chars = v
        out.append({
            "idx": int(idx),
            "category": donor.get("category", ""),
            "description": donor.get("description", "")[:120],
            "use_when": (donor.get("use_when") or "")[:120],
            "max_chars": max_chars,
        })
    return out


def slot_specs_for_layouts(layout_idxs: list[int]) -> dict[str, list[dict[str, Any]]]:
    """Return ``{layout_idx_as_str: [slot_spec, ...]}`` for the requested donors.

    Each ``slot_spec`` is ``{ph_idx, ph_type, safe_max_chars}`` — the
    shape Agent 03 (Content Distributor) expects (see prompt). Donors
    not present in the YAML are skipped; the LLM tolerates missing
    entries (falls back to category heuristics).

    ``layout_idx == 0`` denotes native render (no donor) — also skipped.
    """
    donors = _load()
    out: dict[str, list[dict[str, Any]]] = {}
    for idx in layout_idxs:
        if not idx:  # 0 = native; falsy/None = unset
            continue
        donor = donors.get(int(idx))
        if donor is None:
            continue
        slots = donor.get("slots") or {}
        specs: list[dict[str, Any]] = []
        for slot_name, slot in slots.items():
            if not isinstance(slot, dict):
                continue
            # Translate the YAML's semantic slot name (title/col1_body/etc.)
            # into the OOXML PlaceholderType enum the schema expects. Without
            # this, the LLM mirrors lowercase back and Pydantic rejects every
            # placeholder_assignment (39× failure 2026-06-04 live).
            # schemas.slides._normalize_ph_type also catches edge cases.
            spec = {
                "ph_idx": slot.get("shape_idx"),
                "ph_type": _slot_name_to_ooxml(slot_name),
                "slot_name": slot_name,  # keep original for debug / future use
                "safe_max_chars": slot.get("safe_max_chars") or slot.get("max_chars"),
            }
            # Drop slots without a shape_idx — meaningless to the distributor.
            if spec["ph_idx"] is None:
                continue
            specs.append(spec)
        if specs:
            out[str(int(idx))] = specs
    return out


def slot_name_by_ph_idx(layout_idx: int) -> dict[int, str]:
    """Return ``{ph_idx: slot_name}`` for a single donor.

    ``assemble_plan_node`` uses this to translate the ph_idx values
    produced by the Distributor into the canonical slot names
    ``build_v9`` expects in ``PlanSlide.slots``.
    """
    donors = _load()
    donor = donors.get(int(layout_idx))
    if donor is None:
        return {}
    slots = donor.get("slots") or {}
    out: dict[int, str] = {}
    for name, slot in slots.items():
        if isinstance(slot, dict) and slot.get("shape_idx") is not None:
            out[int(slot["shape_idx"])] = name
    return out


__all__ = [
    "slot_specs_for_layouts",
    "slot_name_by_ph_idx",
    "reload",
    "valid_donor_ids",
    "category_equivalence",
    "tone_groups",
    "default_donor_for_category",
    "donor_summary",
]
