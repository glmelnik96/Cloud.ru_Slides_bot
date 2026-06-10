"""End-to-end driver for the HTML-render pipeline (Path B), host-side.

Reuses the medium-agnostic front-end (parse → brief → classify) verbatim from
the donor pipeline, then runs the HTML back-end: per-slide content → LLM HTML
compose → Chromium render → pack PNGs into a .pptx. Bypasses Telegram/Celery/
Redis so it can validate against real Cloud.ru on the host.

Usage: python -m scripts.html_deck [input.pptx]

Touches no existing pipeline: front-end nodes are imported read-only; all output
lands in tmp/html_out/.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)
if not os.getenv("CLOUDRU_API_KEY"):
    load_dotenv(REPO_ROOT.parent / "Slides_bot" / ".env", override=True)

from langgraph.graph import END, START, StateGraph  # noqa: E402

from graph.designer.planner import (  # noqa: E402
    archetype_for,
    slide_content_for,
)
from graph.nodes.agents import brief_node, classify_node  # noqa: E402
from graph.nodes.pipeline import parse_node  # noqa: E402
from renderers.html.compose import compose_slide  # noqa: E402
from renderers.html.fidelity import snap_payload  # noqa: E402
from renderers.html.pack import pack_pngs  # noqa: E402
from renderers.html.qa import critic_gate, judge_slide  # noqa: E402
from renderers.html.render import SlideRenderer, load_brand_css  # noqa: E402
from schemas.session import SessionInput, SessionState  # noqa: E402

OUT_DIR = REPO_ROOT / "tmp" / "html_out"

# One repair attempt per gate per slide (bounded cost, mirrors /design).
CRITIC_REPAIR_BUDGET = 1
VISION_REPAIR_BUDGET = 1


def _front_end(input_path: str) -> dict:
    """Run parse → brief → classify on the host (no checkpointer / Redis)."""
    g = StateGraph(SessionState)
    g.add_node("parse", parse_node)
    g.add_node("brief", brief_node)
    g.add_node("classify", classify_node)
    g.add_edge(START, "parse")
    g.add_edge("parse", "brief")
    g.add_edge("brief", "classify")
    g.add_edge("classify", END)
    compiled = g.compile()

    inp = SessionInput(
        user_id=0, chat_id=0, progress_message_id=0,
        mode="design", input_s3_key=input_path,
    )
    state = SessionState.from_input(inp)
    print(f"session_id: {state.session_id}", flush=True)
    final = compiled.invoke(state.model_dump())
    return final.get("artefacts") or {}


def main() -> int:
    if not os.getenv("CLOUDRU_API_KEY"):
        print("ERROR: CLOUDRU_API_KEY missing from .env", file=sys.stderr)
        return 2

    input_path = sys.argv[1] if len(sys.argv) > 1 else str(
        REPO_ROOT / "tmp" / "live_inputs" / "6851c8d0f0674088.pptx"
    )
    if not Path(input_path).is_file():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 2
    print(f"input: {input_path}", flush=True)
    print("-" * 80, flush=True)

    t0 = time.monotonic()
    arts = _front_end(input_path)
    classification = arts.get("classification") or {}
    brief = arts.get("brief") or {}
    parsed_by_num = {
        int(s.get("num", 0)): s
        for s in ((arts.get("parsed_deck") or {}).get("slides") or [])
    }
    cls_slides = classification.get("slides") or []
    brief_by_num = {int(s.get("num", 0)): s for s in (brief.get("slides") or [])}
    print(f"classified slides: {len(cls_slides)}  ({time.monotonic()-t0:.1f}s)", flush=True)

    brand_css = (REPO_ROOT / "renderers" / "html" / "brand.css").read_text(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = Path(input_path).stem

    import json as _json  # debug trail for content-fidelity defects
    (OUT_DIR / f"{stem}_frontend.json").write_text(
        _json.dumps({"classification": classification, "brief": brief},
                    ensure_ascii=False, indent=1),
        encoding="utf-8")

    pngs: list[bytes] = []
    with SlideRenderer(load_brand_css()) as renderer:
        for i, cls in enumerate(cls_slides):
            num = int(cls.get("num") or (i + 1))
            archetype = archetype_for(cls, is_first=(i == 0))
            content = slide_content_for(cls, brief_by_num.get(num))
            has_text = bool((content.get("title") or "").strip()) or any(
                str(b).strip() for b in (content.get("body") or [])
            )
            has_native = any(content.get(k) for k in ("kpi", "chart", "table", "flow", "image"))
            if not has_text and not has_native:
                print(f"  slide {num}: phantom — skipped", flush=True)
                continue

            payload = snap_payload({**content, "archetype": archetype},
                                   parsed_by_num.get(num))
            body = compose_slide(payload, brand_css)

            # Gate 1: brand critic on the HTML (canon violations).
            for _ in range(CRITIC_REPAIR_BUDGET):
                cv = critic_gate(body, payload)
                if cv.verdict == "READY":
                    break
                print(f"  slide {num}: critic NOT-READY — {'; '.join(cv.reasons)[:160]}",
                      flush=True)
                body = compose_slide(payload, brand_css, feedback=cv.reasons)

            # Gate 2: vision pixel-judge on the render (keep-better repair).
            png = renderer.render(body)
            for _ in range(VISION_REPAIR_BUDGET):
                pv = judge_slide(payload, png, archetype)
                if pv.ok:
                    break
                print(f"  slide {num}: judge NOT-OK — {'; '.join(pv.issues)[:160]}",
                      flush=True)
                cand_body = compose_slide(payload, brand_css, feedback=pv.issues)
                cand_png = renderer.render(cand_body)
                cand_pv = judge_slide(payload, cand_png, archetype)
                if cand_pv.ok or len(cand_pv.issues) <= len(pv.issues):
                    body, png = cand_body, cand_png
                    print(f"  slide {num}: repaired (judge ok={cand_pv.ok})", flush=True)
                else:
                    print(f"  slide {num}: repair worse — keeping original", flush=True)
                break  # budget=1: one repair round either way

            (OUT_DIR / f"{stem}_s{num:02d}.html").write_text(body, encoding="utf-8")
            (OUT_DIR / f"{stem}_s{num:02d}.png").write_bytes(png)
            pngs.append(png)
            print(f"  slide {num}: {archetype:<16} done ({len(body)} chars)", flush=True)

    if not pngs:
        print("no renderable slides", file=sys.stderr)
        return 1

    out_pptx = OUT_DIR / f"{stem}_html.pptx"
    pack_pngs(pngs, out_pptx)
    elapsed = time.monotonic() - t0
    print("-" * 80, flush=True)
    print(f"built: {out_pptx} ({out_pptx.stat().st_size} bytes)", flush=True)
    print(f"PNGs:  {OUT_DIR}/{stem}_s*.png", flush=True)
    print(f"elapsed: {elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
