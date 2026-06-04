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


@lru_cache(maxsize=1)
def _load() -> dict[int, dict[str, Any]]:
    """Parse donor-slot-map.yaml and return ``{donor_idx: donor_record}``.

    Donor IDs in the YAML are YAML integer keys; PyYAML returns them as
    ``int``. We keep that type so callers can lookup with the same
    ``layout_idx`` value that flows through LayoutPlan.
    """
    path = _map_path()
    if not path.is_file():
        raise FileNotFoundError(f"donor-slot-map missing: {path}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    donors = raw.get("donors") or {}
    # Normalise keys to int — defensive in case anyone writes "4" in YAML.
    return {int(k): v for k, v in donors.items() if v}


def reload() -> None:
    """Drop the cached map. Use in tests when the YAML changes on disk."""
    _load.cache_clear()


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
            spec = {
                "ph_idx": slot.get("shape_idx"),
                "ph_type": slot_name,
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


__all__ = ["slot_specs_for_layouts", "slot_name_by_ph_idx", "reload"]
