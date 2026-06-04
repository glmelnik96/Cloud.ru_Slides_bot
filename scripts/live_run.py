"""One-shot live validation driver.

Bypasses Telegram + Celery and runs the LangGraph pipeline directly on the
host against real Cloud.ru. Uses skill_assets/Cloud.ru_Template_2026.pptx
as input (the deck is both the user-draft and the donor template — same
pattern as the offline e2e test).

Stubs Redis pub/sub to print to stdout so we can watch stages live.

Usage: python -m scripts.live_run
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root before any module reads env vars.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env", override=True)

from graph.graph import _build_graph  # noqa: E402
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

    # Wire progress to stdout instead of Redis.
    progress.publish = _print_event  # type: ignore[assignment]

    # Build a session pointing at a small synthetic draft deck. The donor
    # template (88 slides) is NOT a sensible user input — it's the library.
    skill_bridge.install()
    input_path = os.environ.get("LIVE_RUN_INPUT") or "C:/Users/Глеб/AppData/Local/Temp/test_draft.pptx"
    if not Path(input_path).is_file():
        print(f"ERROR: input draft not found: {input_path}\n"
              f"Generate with: python -m scripts.make_test_deck {input_path}",
              file=sys.stderr)
        return 2
    inp = SessionInput(
        user_id=0, chat_id=0, progress_message_id=0,
        mode="verstai",
        input_s3_key=input_path,
    )
    state = SessionState.from_input(inp)
    print(f"session_id: {state.session_id}", flush=True)
    print(f"input:      {state.input_s3_key}", flush=True)
    print(f"template:   {skill_bridge.TEMPLATE_PATH}", flush=True)
    print("-" * 80, flush=True)

    # Compile graph WITHOUT a checkpointer — no Redis dependency for this run.
    graph = _build_graph().compile()
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
    print(f"elapsed:    {elapsed:.1f}s", flush=True)

    arts = final.get("artefacts") or {}
    print(f"final stage:    {final.get('stage')}", flush=True)
    print(f"progress_pct:   {final.get('progress_pct')}", flush=True)
    print(f"brand_score:    {final.get('brand_score')}", flush=True)
    print(f"errors:         {final.get('errors')}", flush=True)
    print(f"artefact keys:  {sorted(arts.keys())}", flush=True)

    built = arts.get("built_pptx_path")
    if built:
        p = Path(built)
        print(f"built .pptx:    {p} ({p.stat().st_size} bytes)" if p.is_file()
              else f"built .pptx:    MISSING ({built})", flush=True)

    plan = arts.get("plan") or {}
    plan_slides = plan.get("slides") if isinstance(plan, dict) else None
    print(f"plan slides:    {len(plan_slides) if plan_slides else 0}", flush=True)

    brand = arts.get("brand_report") or {}
    if isinstance(brand, dict):
        print(f"brand verdict:  {brand.get('verdict')} score={brand.get('score')}", flush=True)

    vv = arts.get("visual_verdict") or {}
    if isinstance(vv, dict):
        print(f"visual verdict: {vv.get('llm_verdict')} score_avg={vv.get('score_avg')}", flush=True)

    ver = arts.get("verifier_verdict") or {}
    if isinstance(ver, dict):
        print(f"final verdict:  {ver.get('verdict')}", flush=True)

    return 0 if final.get("stage") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
