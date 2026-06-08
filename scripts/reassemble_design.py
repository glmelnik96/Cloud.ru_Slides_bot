"""Re-assemble a designer deck from a persisted Composition (DSL) dump.

Assembly (DSL -> native .pptx) is fully deterministic, so iterating on the
``native_assembler`` does NOT require another paid LLM run: re-run this on the
``<session>_comp.json`` dump written by ``scripts.live_run_design``.

Usage: python -m scripts.reassemble_design tmp/design_out/<session>_comp.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from renderers.designer.composition_dsl import Composition
from renderers.designer.native_assembler import build_deck

# Put the skill scripts (textfit / font_resolver) on sys.path so the assembler's
# shrink-to-fit is IDENTICAL to a live run. Without this the textfit import in
# primitives._fit silently fails and titles/body render at base_pt (unfitted),
# which makes reassembly diverge from the real pipeline output (e.g. long titles
# overflow their box). Mirrors scripts.live_run_design.
from worker import skill_bridge  # noqa: E402


def main() -> int:
    skill_bridge.install()
    if len(sys.argv) < 2:
        print("usage: python -m scripts.reassemble_design <comp.json>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    if not src.is_file():
        print(f"ERROR: comp dump not found: {src}", file=sys.stderr)
        return 2

    comps_raw = json.loads(src.read_text(encoding="utf-8"))
    comps = [Composition.model_validate(c) for c in comps_raw]
    out = src.with_name(src.name.replace("_comp.json", "_reassembled.pptx"))
    build_deck(comps, str(out))
    p = Path(out)
    print(f"reassembled: {p} ({p.stat().st_size} bytes)" if p.is_file()
          else f"FAILED: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
