"""One-shot live validation driver for the /design (from-scratch) skill.

Mirror of ``scripts.live_run`` but drives the standalone designer graph
(parse → brief → classify → art_director → compose → native_assemble) against
real Cloud.ru, bypassing Telegram + Celery + Redis.

Usage: python -m scripts.live_run_design [input.pptx]
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env: prefer the worktree's own, fall back to the sibling main repo
# (git worktrees share the project but not untracked secrets).
REPO_ROOT = Path(__file__).resolve().parent.parent
_loaded = load_dotenv(REPO_ROOT / ".env", override=True)
if not os.getenv("CLOUDRU_API_KEY"):
    load_dotenv(REPO_ROOT.parent / "Slides_bot" / ".env", override=True)

from graph.designer.graph import build_designer_graph  # noqa: E402
from schemas.session import ProgressEvent, SessionInput, SessionState  # noqa: E402
from worker import progress, skill_bridge  # noqa: E402


def _print_event(ev: ProgressEvent) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    tag = "TERM" if ev.terminal else "STG "
    print(f"[{ts}] {tag} {ev.stage:<14} {ev.progress_pct:>3}%  {ev.detail}", flush=True)
    if ev.error:
        print(f"           error: {ev.error}", flush=True)
    if ev.terminal and ev.result_path:
        print(f"           result_path: {ev.result_path}", flush=True)


def main() -> int:
    if not os.getenv("CLOUDRU_API_KEY"):
        print("ERROR: CLOUDRU_API_KEY missing from .env", file=sys.stderr)
        return 2

    progress.publish = _print_event  # type: ignore[assignment]
    skill_bridge.install()

    input_path = (
        sys.argv[1] if len(sys.argv) > 1
        else os.environ.get("LIVE_RUN_INPUT")
        or "C:/Users/Глеб/AppData/Local/Temp/test_draft.pptx"
    )
    if not Path(input_path).is_file():
        print(f"ERROR: input draft not found: {input_path}", file=sys.stderr)
        return 2

    inp = SessionInput(
        user_id=0, chat_id=0, progress_message_id=0,
        mode="design",
        input_s3_key=input_path,
    )
    state = SessionState.from_input(inp)
    print(f"session_id: {state.session_id}", flush=True)
    print(f"input:      {state.input_s3_key}", flush=True)
    print("-" * 80, flush=True)

    graph = build_designer_graph().compile()  # no checkpointer — no Redis
    t0 = time.monotonic()
    try:
        final = graph.invoke(state.model_dump())
    except Exception as e:  # noqa: BLE001
        print(f"\nPIPELINE CRASHED: {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 1
    elapsed = time.monotonic() - t0
    print("-" * 80, flush=True)
    print(f"elapsed:        {elapsed:.1f}s", flush=True)

    arts = final.get("artefacts") or {}
    print(f"final stage:    {final.get('stage')}", flush=True)
    print(f"progress_pct:   {final.get('progress_pct')}", flush=True)
    print(f"errors:         {final.get('errors')}", flush=True)
    print(f"artefact keys:  {sorted(arts.keys())}", flush=True)

    stub = arts.get("design_stub") or {}
    if isinstance(stub, dict) and stub:
        print(f"design_stub:    tonality={stub.get('tonality')} "
              f"dark_ratio={stub.get('dark_ratio')} "
              f"motif={stub.get('motif_mix')}", flush=True)

    comps = arts.get("compositions") or []
    print(f"compositions:   {len(comps)}", flush=True)
    for c in comps:
        blocks = c.get("blocks") or []
        roles = [b.get("role") for b in blocks]
        print(f"  slide {c.get('slide_num')}: tone={c.get('tone')} "
              f"blocks={len(blocks)} roles={roles}", flush=True)

    built = arts.get("result_path")
    if built:
        p = Path(built)
        print(f"built .pptx:    {p} ({p.stat().st_size} bytes)" if p.is_file()
              else f"built .pptx:    MISSING ({built})", flush=True)

    return 0 if final.get("stage") in ("done", "finalizing") else 1


if __name__ == "__main__":
    sys.exit(main())
