"""Python-script nodes — wrap vendored skill scripts (no LLM calls).

Each node:
- Reads the upstream artefact it needs (raises if missing).
- Emits a progress event.
- Writes its output under a stable artefacts[] key.

Output shapes are typed through the corresponding Pydantic model in
``schemas/slides.py`` wherever feasible.

Pending wiring (S3 round-trip for input/output, donor-slot-map loading
inside distribute_node, LibreOffice render, native chart engine) is
tracked by inline FIXME(next-chunk) comments.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import structlog

from schemas.session import SessionState, Stage
from schemas.slides import (
    BrandReport,
    ParsedDeck,
    Plan,
    PlanSlide,
    VerifierVerdict,
)
from worker import progress, skill_bridge

logger = structlog.get_logger(__name__)


def _artefacts(state: SessionState) -> dict[str, Any]:
    return dict(state.artefacts)


def _emit(state: SessionState, stage: Stage, pct: int, detail: str) -> None:
    progress.stage(state.session_id, stage, pct=pct, detail=detail)


def _resolve_input_path(state: SessionState) -> Path | None:
    """Locate the input draft on disk.

    Resolution order (M3 interim — S3 layer lands in M5):
        1. ``state.artefacts['input_path']`` — explicit override used by
           integration tests and the local-disk worker path.
        2. ``state.input_s3_key`` — treated as a local path while
           ``storage/s3.py`` is not yet implemented. The schema field
           keeps its name so the contract with the bot doesn't churn.
    Returns ``None`` if neither is set or the path does not exist.
    """
    override = state.artefacts.get("input_path") if state.artefacts else None
    candidates = [override, state.input_s3_key]
    for c in candidates:
        if not c:
            continue
        p = Path(str(c))
        if p.is_file():
            return p
    return None


def _render_first_slide_png(pptx_path: Path) -> str | None:
    """Render slide 1 of ``pptx_path`` to PNG via LibreOffice headless.

    Runs ``render_slides.py`` in a subprocess so its ``sys.exit(1)`` on
    failure (used by the vendored script) doesn't tear down the worker.
    Returns the absolute PNG path as a string (consumable by
    ``llm.client.VisionImage = str | bytes | Path``) or ``None`` if
    LibreOffice / pdftoppm aren't available — Brief Reader degrades to
    its 1×1 placeholder grounding.
    """
    script = Path(skill_bridge.SKILL_SCRIPTS) / "render_slides.py"
    if not script.is_file():  # pragma: no cover — vendored file guaranteed
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="slidesbot_render_"))
    try:
        result = subprocess.run(
            [sys.executable, str(script), str(pptx_path), str(out_dir)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            logger.warning("node.parse.render_failed",
                           stderr=result.stderr[-500:] if result.stderr else "")
            shutil.rmtree(out_dir, ignore_errors=True)
            return None
        pngs = sorted(out_dir.glob("slide*.png"))
        if not pngs:
            shutil.rmtree(out_dir, ignore_errors=True)
            return None
        # Keep only slide 1 — Kimi grounding needs one anchor; per-deck
        # cost balloons fast if we ship every slide upstream.
        first = pngs[0]
        return str(first)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("node.parse.render_unavailable", error=str(e))
        shutil.rmtree(out_dir, ignore_errors=True)
        return None


# ─── parse_node ──────────────────────────────────────────────────────────────

def parse_node(state: SessionState) -> dict[str, Any]:
    """Parse the uploaded draft into ``ParsedDeck`` (artefacts['parsed_deck']).

    Verstai/audit modes ship a .pptx. Brief mode (.docx) and a future
    markdown path are gated: their classified-slide shape is unrelated
    to ``ParsedDeck`` and lands with M5 (three modes).

    Side effect: renders slide 1 to PNG (subprocess, LibreOffice
    headless) and stores its path under ``artefacts['original_pngs']``
    for Brief Reader vision grounding. Best-effort — skipped silently
    if soffice/pdftoppm aren't on the host.

    FIXME(next-chunk):
        * Pull input bytes from S3 once ``storage/s3.py`` lands; for now
          ``state.input_s3_key`` is treated as a local path.
        * Wire .docx / .md branches when M5 brief mode arrives — they
          should populate ``artefacts['classified_deck']`` instead.
        * Honour the 50 MB Telegram cap once the bot persists files.
    """
    _emit(state, Stage.PARSING, pct=5, detail="разбор файла")
    arts = _artefacts(state)

    path = _resolve_input_path(state)
    if path is None:
        raise RuntimeError(
            "parse_node: no input file — set state.input_s3_key (local path "
            "until S3 lands) or artefacts['input_path']"
        )

    ext = path.suffix.lower()
    if ext != ".pptx":
        raise NotImplementedError(
            f"parse_node: only .pptx supported in M3 (got {ext}); "
            ".docx/.md land with M5 brief mode"
        )

    skill_bridge.install()
    import parse_pptx  # vendored — sys.path mounted by skill_bridge

    raw = parse_pptx.parse(str(path))
    # parse_pptx writes 'slide_size' with width_emu/height_emu keys; ParsedDeck
    # has model_config extra='allow' so the extra keys roundtrip.
    deck = ParsedDeck.model_validate(raw)
    arts["parsed_deck"] = deck.model_dump()

    png = _render_first_slide_png(path)
    if png is not None:
        arts["original_pngs"] = [png]
    else:
        # Leave the key unset — brief_node already falls back to a 1×1
        # placeholder when 'original_pngs' is absent.
        arts.pop("original_pngs", None)

    logger.info(
        "node.parse.done",
        session_id=state.session_id,
        path=str(path),
        slide_count=deck.slide_count,
        grounded=png is not None,
    )
    return {"artefacts": arts, "stage": Stage.PARSING.value, "progress_pct": 10}


# ─── assemble_plan_node ──────────────────────────────────────────────────────

_NATIVE_BLOCK_KEYS = ("kpi", "chart", "table", "flow", "image")


def _sanitize_native_block(slide_type: str, key: str, block: Any) -> Any:
    """Patch known shape mismatches between classifier output and vendored
    renderers in skill_assets/scripts/.

    These come from prompt-tuning gaps in Agent 02 — the right long-term
    fix is to tighten the classifier system prompt and re-capture cassettes.
    Until then, sanitize at the orchestration boundary so build_v9 has a
    fighting chance:

    * flow_diagram_native with ``grid=false`` AND no explicit x/y/w/h on any
      block: force ``grid=true`` so ``flow_renderer.compose_grid`` derives
      coords from row/col defaults. Blocks then stack but at least render.
    """
    if not isinstance(block, dict):
        return block
    if key == "flow" and slide_type == "flow_diagram_native":
        # Preset archetypes own their layout — flow_renderer dispatches to the
        # preset function and returns before the grid/blocks path. Forcing
        # grid=true here would be a no-op at best, so leave preset blocks alone.
        if (block.get("preset") or "").strip():
            return block
        blocks = block.get("blocks") or []
        if not block.get("grid"):
            has_coords = all(
                isinstance(b, dict) and all(b.get(c) is not None for c in ("x", "y", "w", "h"))
                for b in blocks
            ) if blocks else False
            if not has_coords:
                block = dict(block)
                block["grid"] = True
                # cols default — flow_renderer derives from blocks if absent,
                # but supplying a sane fallback avoids divide-by-zero edges.
                if not block.get("cols"):
                    block["cols"] = max(1, min(len(blocks), 4))
    return block


def _native_block_is_usable(slide_type: str, cls: dict[str, Any]) -> bool:
    """True iff the classifier supplied enough data for build_v9 to render
    the native ``slide_type`` without crashing.

    Build_v9 raises ValueError on empty headers/data/series — that takes down
    the whole pipeline. Detecting it here lets ``assemble_plan_node`` skip
    just the offending slide and keep the rest of the deck.

    Empirical: Agent 02 (Slide Classifier) sometimes picks ``table_native``
    for a slide where the source draft has no tabular data, leaving the
    ``table`` block as ``{"header": "…", "subtitle": "", "style": "…"}``
    with no ``headers`` / ``data``. Same pattern observed for chart_pptx and
    kpi natives.
    """
    if slide_type == "table_native":
        tbl = cls.get("table") or {}
        if not isinstance(tbl, dict):
            return False
        if not (tbl.get("headers") or []):
            return False
        if not (tbl.get("data") or []):
            return False
        return True
    if slide_type == "chart_pptx_native":
        chart = cls.get("chart") or {}
        if not isinstance(chart, dict):
            return False
        if not (chart.get("series") or []):
            return False
        return True
    if slide_type == "kpi_native":
        kpi = cls.get("kpi") or {}
        if not isinstance(kpi, dict):
            return False
        nums = kpi.get("numbers") or []
        if not nums:
            return False
        # Belt-and-braces: kpi_renderer.render_kpi() hard-caps at 3 numbers
        # and raises ValueError otherwise — taking down the whole pipeline.
        # classify_node._coerce_overflow_kpis is the primary truncation
        # site; this mutation here catches any path that bypasses it
        # (e.g. autofix loop re-injecting numbers, future agent additions).
        if len(nums) > 3:
            kpi["numbers"] = nums[:3]
            cls["kpi"] = kpi
        return True
    if slide_type == "flow_diagram_native":
        flow = cls.get("flow") or {}
        if not isinstance(flow, dict):
            return False
        # Preset archetypes (card_grid / numbered_rows / numbered_columns /
        # hero_statement) carry their content in preset-specific keys, NOT in
        # the generic `blocks` list. Treat the slide as buildable when the
        # preset's required data is present (flow_renderer reads these keys).
        preset = (flow.get("preset") or "").strip()
        if preset:
            preset_data_keys = {
                "card_grid": "cards",
                "numbered_rows": "rows",
                "numbered_columns": "columns",
                "hero_statement": "statement",
            }
            data_key = preset_data_keys.get(preset)
            if data_key is None:
                # Unknown preset → fall through to blocks check below.
                pass
            elif flow.get(data_key):
                return True
            else:
                return False
        if not (flow.get("blocks") or []):
            return False
        return True
    if slide_type == "image_native":
        img = cls.get("image") or {}
        if not isinstance(img, dict):
            return False
        if not (img.get("image_path") or img.get("path")):
            return False
        return True
    # Unknown slide_type → let build_v9 try; if it crashes we'll widen this.
    return True


def _by_num(items: list[dict[str, Any]], key: str = "num") -> dict[int, dict[str, Any]]:
    """Index a list of slide-shaped dicts by their slide number key.

    Different agent outputs use different number keys: Classifier/Layouts
    use ``num``, Distributor/Copy Editor use ``slide_num``. Pass the
    right key per source.
    """
    out: dict[int, dict[str, Any]] = {}
    for item in items or []:
        n = item.get(key) if isinstance(item, dict) else None
        if isinstance(n, int):
            out[n] = item
    return out


def assemble_plan_node(state: SessionState) -> dict[str, Any]:
    """Fold classification + layouts + copy-edited content + icons +
    infographics into a single ``Plan`` consumable by ``build_v9.py``.

    For each slide:
        * Classification.slide_type set → native PlanSlide carrying the
          matching kpi/chart/table/flow/image block + ``dark``.
        * Otherwise → donor PlanSlide(clone_from_slide=layout_idx,
          slots, slot_styles_override). Slot keys are translated from
          ``ph_idx`` to canonical slot names via
          ``donor_map.slot_name_by_ph_idx`` so build_v9 finds them.
        * Infographic shapes (Agent 06) for non-``none`` types are
          attached under the ``infographic`` extra field. ``PlanSlide``
          uses ``extra='allow'``, so build_v9 sees the key verbatim.
        * Icon assignments are attached the same way under ``icons``.

    Slides Classifier rejected as ``slide_type=None`` AND with no donor
    (layout_idx=0 + no native block) are skipped with a warning — they
    are unbuildable.
    """
    from graph import donor_map  # noqa: WPS433 — keep cycle local

    _emit(state, Stage.DESIGNING, pct=78, detail="сборка плана")
    arts = _artefacts(state)

    classification_slides = (arts.get("classification") or {}).get("slides", [])
    layouts_slides = (arts.get("layouts") or {}).get("slides", [])
    # copy_edited is the cleaned form of `content` — prefer it; fall back.
    content_src = arts.get("copy_edited") or arts.get("content") or {}
    content_slides = content_src.get("slides", [])
    infographics_slides = (arts.get("infographics") or {}).get("slides", [])
    icons_slides = (arts.get("icons") or {}).get("slides", [])

    # D3 fix (2026-06-05): brief-derived title fallback for donor slides
    # whose distributor output omits the title placeholder. Live run2.slide1
    # rendered the cover with empty title because Agent 03 emitted no
    # placeholder_assignment for ph_idx=1 of donor 4 — the slot stayed empty
    # and build_v9 cleared the donor's "Заголовок" placeholder text. Source
    # of truth for the topic is brief.topic (deck title) and BriefSlide
    # .raw_title (per-slide title).
    brief_data = arts.get("brief") or {}
    brief_topic = (brief_data.get("topic") or "").strip()
    brief_slides_by_num: dict[int, str] = {}
    for bs in (brief_data.get("slides") or []):
        if isinstance(bs, dict):
            n = bs.get("num")
            rt = (bs.get("raw_title") or "").strip()
            if isinstance(n, int) and rt:
                brief_slides_by_num[n] = rt

    cls_by_num = _by_num(classification_slides, key="num")
    lay_by_num = _by_num(layouts_slides, key="num")
    content_by_num = _by_num(content_slides, key="slide_num")
    info_by_num = _by_num(infographics_slides, key="slide_num")
    icons_by_num = _by_num(icons_slides, key="slide_num")

    plan_slides: list[PlanSlide] = []
    skipped: list[int] = []

    # Drive by classification (canonical slide order). Each classification
    # slide either lands as a donor PlanSlide or a native one.
    for cls in classification_slides:
        if not isinstance(cls, dict):
            continue
        num = cls.get("num")
        if not isinstance(num, int):
            continue

        slide_type = cls.get("slide_type")
        layout = lay_by_num.get(num) or {}
        donor = layout.get("layout_idx") or layout.get("donor") or 0

        try:
            if slide_type:
                # Native route — carry the matching data block straight from
                # classification (Agent 02 produces typed blocks per slide_type).
                # Skip if the classifier under-filled the native block — better
                # to lose one slide than crash the whole deck inside build_v9.
                if not _native_block_is_usable(slide_type, cls):
                    logger.warning("node.assemble.native_block_empty",
                                   session_id=state.session_id,
                                   num=num, slide_type=slide_type)
                    skipped.append(num)
                    continue
                kwargs: dict[str, Any] = {
                    "slide_type": slide_type,
                    "dark": bool(cls.get("dark", False)),
                }
                for k in _NATIVE_BLOCK_KEYS:
                    block = cls.get(k)
                    if block is not None:
                        kwargs[k] = _sanitize_native_block(slide_type, k, block)
                ps = PlanSlide(**kwargs)
            else:
                if not donor:
                    # Classifier left slide_type empty AND Designer routed
                    # to native (donor=0). Nothing to build — skip.
                    skipped.append(num)
                    continue
                # Donor route — translate ph_idx → canonical slot name.
                slot_name_map = donor_map.slot_name_by_ph_idx(int(donor))
                if not slot_name_map:
                    # Donor isn't in donor-slot-map.yaml — build_v9 won't
                    # match any slots and template defaults will leak through.
                    # design_node should have caught this; log loudly so we
                    # can extend the YAML or tighten the designer.
                    logger.warning(
                        "node.assemble.donor_unmapped",
                        session_id=state.session_id,
                        num=num,
                        donor=int(donor),
                    )
                cont = content_by_num.get(num) or {}
                phs = cont.get("placeholder_assignments") or []
                slots: dict[str, Any] = {}
                for pa in phs:
                    if not isinstance(pa, dict):
                        continue
                    ph_idx = pa.get("ph_idx")
                    name = slot_name_map.get(int(ph_idx)) if isinstance(ph_idx, int) else None
                    # If donor schema doesn't know this ph_idx, key by the raw
                    # index — build_v9 will warn but still surface the content.
                    key = name or (f"ph_{ph_idx}" if ph_idx is not None else None)
                    if key is None:
                        continue
                    slots[key] = pa.get("content", "")

                # D3 fix (2026-06-05): if the donor has a "title" slot but
                # the Distributor never assigned it, fall back to per-slide
                # raw_title from brief, then deck topic for slide 1. Without
                # this, build_v9 clears the donor's "Заголовок" placeholder
                # and the slide renders with an empty title bar.
                donor_slot_names = set(slot_name_map.values())
                if "title" in donor_slot_names and not (slots.get("title") or "").strip():
                    fallback = brief_slides_by_num.get(num) or (
                        brief_topic if num == 1 else ""
                    )
                    if fallback:
                        slots["title"] = fallback
                        logger.info(
                            "node.assemble.title_fallback",
                            session_id=state.session_id,
                            num=num, donor=int(donor),
                            source="brief.raw_title" if num in brief_slides_by_num else "brief.topic",
                        )

                ps = PlanSlide(
                    clone_from_slide=int(donor),
                    slots=slots,
                    slot_styles_override=layout.get("slot_styles_override") or {},
                )
        except Exception as e:  # noqa: BLE001 — Pydantic ValidationError + lookups
            logger.warning("node.assemble.slide_skip",
                           session_id=state.session_id, num=num, error=str(e))
            skipped.append(num)
            continue

        # Attach Agent 06 infographic shapes for slides where they apply.
        info = info_by_num.get(num) or {}
        info_type = info.get("infographic_type")
        if info_type and info_type != "none":
            ps_dump = ps.model_dump()
            ps_dump["infographic"] = {
                "type": info_type,
                "shapes": info.get("shapes") or [],
            }
            # Re-validate so the extras roundtrip cleanly through Plan.
            ps = PlanSlide.model_validate(ps_dump)

        # Attach icon assignments (Agent 05) under a single 'icons' key.
        # Drop entries whose icon_path is null — the SVG library hasn't been
        # populated yet (only brand_arrow.svg ships with M2), so unresolved
        # picks would land in the plan as "ghost icons" that build_v9 can't
        # render. Visual Verifier then reports them as plan↔PNG mismatches.
        icon_entry = icons_by_num.get(num) or {}
        icon_assigns = [
            a for a in (icon_entry.get("icon_assignments") or [])
            if a.get("icon_path")
        ]
        if icon_assigns:
            ps_dump = ps.model_dump()
            ps_dump["icons"] = icon_assigns
            ps = PlanSlide.model_validate(ps_dump)

        plan_slides.append(ps)

    plan = Plan(slides=plan_slides)
    arts["plan"] = plan.model_dump()
    logger.info(
        "node.assemble.done",
        session_id=state.session_id,
        slides=len(plan_slides),
        skipped=skipped,
    )
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 80}


# ─── build_node — skeleton ───────────────────────────────────────────────────

def _session_workdir(session_id: str) -> Path:
    """Per-session scratch dir.

    Created lazily; not cleaned up between nodes so subsequent nodes
    (build → brand → render) can share artefacts on disk. The worker's
    session-end cleanup hook (M3 close-out) will own teardown.

    Honors ``SLIDESBOT_WORKDIR`` so bot and worker containers can share
    a volume — without this the worker writes ``result.pptx`` to its own
    ``/tmp`` and the bot's send_document on terminal DONE can't see it.
    """
    root = os.environ.get("SLIDESBOT_WORKDIR") or str(Path(tempfile.gettempdir()) / "slidesbot")
    d = Path(root) / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_node(state: SessionState) -> dict[str, Any]:
    """Call ``build_v9.build()`` with the assembled Plan, write output to
    the per-session workdir, and record its path under
    ``artefacts['built_pptx_path']``.

    S3 upload lands with M5 (storage/s3.py). For M3 the worker keeps the
    file on local disk and downstream nodes (brand_guard, render_png)
    read from the same path. ``state.result_s3_key`` is set to the path
    string as an interim so the bot side can pick it up via the same
    field once S3 is wired.

    FIXME(next-chunk):
        * Replace local-path stash with S3 upload — populate
          ``state.result_s3_key`` with a real key.
    """
    import json as _json  # local — not used elsewhere in this module

    _emit(state, Stage.RENDERING, pct=82, detail="сборка pptx")
    arts = _artefacts(state)
    plan = arts.get("plan")
    if not plan:
        raise RuntimeError("build_node: artefacts['plan'] missing — assemble_plan_node didn't run")

    skill_bridge.install()
    import build_v9  # vendored

    workdir = _session_workdir(state.session_id)
    plan_path = workdir / "plan.json"
    out_path = workdir / "result.pptx"
    # Strip explicit nulls before handing off to vendored build_v9. Several
    # of its renderers do ``cfg.get("key", {})`` which only fires the default
    # when the key is *absent* — an explicit ``null`` (which Pydantic emits
    # for Optional fields with default=None) crashes them. Pydantic-level
    # dump from assemble_plan_node carries those nulls; we drop them here at
    # the boundary so the in-memory state stays canonical.
    #
    # by_alias=True ensures schema fields with Python-keyword aliases
    # (FlowArrow.src→"from", FlowArrow.dst→"to") emit the JSON form that
    # flow_renderer.py reads. Without this, arrows silently disappear.
    plan_for_build = Plan.model_validate(plan).model_dump(
        exclude_none=True, by_alias=True,
    )
    with plan_path.open("w", encoding="utf-8") as f:
        _json.dump(plan_for_build, f, ensure_ascii=False, indent=None)

    build_v9.build(
        str(plan_path),
        str(skill_bridge.TEMPLATE_PATH),
        str(out_path),
        str(skill_bridge.DONOR_SLOT_MAP),
    )
    if not out_path.is_file():
        raise RuntimeError(f"build_node: build_v9 did not produce {out_path}")

    arts["built_pptx_path"] = str(out_path)
    logger.info(
        "node.build.done",
        session_id=state.session_id,
        path=str(out_path),
        size_bytes=out_path.stat().st_size,
    )
    return {
        "artefacts": arts,
        "stage": Stage.RENDERING.value,
        "progress_pct": 84,
        # Interim: surface the local path through the same field S3 will own.
        "result_s3_key": str(out_path),
    }


# ─── brand_guard_node — skeleton ─────────────────────────────────────────────

def _brand_issue_to_dict(item: dict[str, Any], severity: str) -> dict[str, Any]:
    """Translate a brand_guardian violation/warning entry into BrandViolation
    shape (severity / rule / msg / fix). The script tags issues with
    ``type``/``msg``/``fix``/``shape_idx``; we keep the extras (shape_idx)
    through extra='allow'.
    """
    out = dict(item)  # preserve extras (shape_idx, etc.)
    out["severity"] = severity
    out["rule"] = item.get("type", "unknown")
    out["msg"] = item.get("msg", "")
    out["fix"] = item.get("fix", "")
    return out


def brand_guard_node(state: SessionState) -> dict[str, Any]:
    """Run ``brand_guardian.validate_slide`` over each slide of the built
    pptx and aggregate into a ``BrandReport``.

    Per-slide verdict precedence: any violation → FAIL, else any warning
    → WARN, else OK. Deck verdict follows the same precedence over the
    slide list. Score avg is the rounded mean of slide scores.

    The vendored ``brand_guardian.main()`` does CLI I/O and ``sys.exit``;
    we go straight to ``validate_slide`` so we can stay in-process.
    """
    _emit(state, Stage.VALIDATING, pct=85, detail="бренд-проверка")
    arts = _artefacts(state)
    pptx_path = arts.get("built_pptx_path")
    if not pptx_path or not Path(pptx_path).is_file():
        raise RuntimeError(
            f"brand_guard_node: built pptx not found at {pptx_path!r} — "
            "build_node didn't run or produced no output"
        )

    skill_bridge.install()
    import brand_guardian  # vendored
    from pptx import Presentation

    deck = Presentation(pptx_path)
    slide_reports = []
    for i, slide in enumerate(deck.slides, start=1):
        raw = brand_guardian.validate_slide(slide, i)
        violations = [
            _brand_issue_to_dict(v, "FAIL") for v in raw.get("violations", [])
        ]
        warnings = [
            _brand_issue_to_dict(w, "WARN") for w in raw.get("warnings", [])
        ]
        if violations:
            verdict = "FAIL"
        elif warnings:
            verdict = "WARN"
        else:
            verdict = "OK"
        slide_reports.append({
            "slide_num": i,
            "verdict": verdict,
            # BrandViolation list: keep both severities under `violations`.
            # extra='allow' lets us roundtrip warnings under their own key too.
            "violations": violations + warnings,
            "score": int(raw.get("score", 100)),
            "layout_name": raw.get("layout_name", ""),
        })

    # Deck-level rollup
    has_fail = any(s["verdict"] == "FAIL" for s in slide_reports)
    has_warn = any(s["verdict"] == "WARN" for s in slide_reports)
    deck_verdict = "FAIL" if has_fail else ("WARN" if has_warn else "OK")
    score_avg = (
        round(sum(s["score"] for s in slide_reports) / len(slide_reports))
        if slide_reports else 100
    )

    report = BrandReport.model_validate({
        "verdict": deck_verdict,
        "score_avg": score_avg,
        "slides": slide_reports,
    })
    arts["brand_report"] = report.model_dump()
    logger.info(
        "node.brand.done",
        session_id=state.session_id,
        verdict=deck_verdict,
        score_avg=score_avg,
        slides=len(slide_reports),
    )
    return {
        "artefacts": arts,
        "stage": Stage.VALIDATING.value,
        "progress_pct": 87,
        "brand_score": score_avg,
    }


# ─── render_png_node — skeleton ──────────────────────────────────────────────

_MAX_VERIFIER_SLIDES = 20
"""Hard cap on PNGs handed to Visual Verifier. Empirically ~10s per
big-deck Kimi call already; beyond 20 slides verifier accuracy degrades
faster than reasoning budget can compensate (see memory/cloudru_fm_api.md
token budget rule of thumb)."""


def render_png_node(state: SessionState) -> dict[str, Any]:
    """Render the built pptx to per-slide PNGs (LibreOffice headless via
    ``render_slides.py``) and stash the paths under
    ``artefacts['rendered_pngs']`` for the Visual Verifier.

    Capped at ``_MAX_VERIFIER_SLIDES`` to bound Kimi vision cost. Stores
    string paths (``VisionImage = str | bytes | Path`` so the LLM client
    will read them lazily).
    """
    _emit(state, Stage.RENDERING, pct=88, detail="рендер PNG")
    arts = _artefacts(state)
    pptx_path = arts.get("built_pptx_path")
    if not pptx_path or not Path(pptx_path).is_file():
        raise RuntimeError(
            f"render_png_node: built pptx not found at {pptx_path!r}"
        )

    workdir = _session_workdir(state.session_id) / "pngs"
    workdir.mkdir(parents=True, exist_ok=True)

    script = Path(skill_bridge.SKILL_SCRIPTS) / "render_slides.py"
    result = subprocess.run(
        [sys.executable, str(script), str(pptx_path), str(workdir)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        # Soft-fail: Visual Verifier will still run on whatever we managed
        # to render (possibly zero — it then falls back per its prompt).
        logger.warning(
            "node.render_png.soffice_failed",
            session_id=state.session_id,
            stderr=result.stderr[-500:] if result.stderr else "",
        )

    pngs = sorted(workdir.glob("slide*.png"))[:_MAX_VERIFIER_SLIDES]
    arts["rendered_pngs"] = [str(p) for p in pngs]
    logger.info(
        "node.render_png.done",
        session_id=state.session_id,
        rendered=len(pngs),
        capped=len(pngs) == _MAX_VERIFIER_SLIDES,
    )
    return {"artefacts": arts, "stage": Stage.RENDERING.value, "progress_pct": 89}


# ─── process_verify_node — skeleton ──────────────────────────────────────────

def process_verify_node(state: SessionState) -> dict[str, Any]:
    """Agent 09 — synthesise validate_plan errors + brand_guardian +
    LLM Visual Verifier into the single READY / NEEDS_REWORK gate.

    Decision rule:
        * validate_plan error → NEEDS_REWORK (plan is broken upstream).
        * brand verdict == FAIL → NEEDS_REWORK.
        * visual llm_verdict == NEEDS_REWORK → NEEDS_REWORK.
        * else → READY (warnings are surfaced but don't block).

    Per-slide ``checklist_results`` carry per-source issue lists for the
    UI summary; deck ``blockers`` aggregate hard failures, ``warnings``
    everything else.

    M4 will hand a NEEDS_REWORK verdict to an autofix branch; for M3 the
    finalize node just surfaces it to the user.
    """
    _emit(state, Stage.VALIDATING, pct=94, detail="свод проверок")
    arts = _artefacts(state)
    plan = arts.get("plan") or {}
    brand = arts.get("brand_report") or {}
    visual = arts.get("visual_verdict") or {}

    # 1. Re-run validate_plan for the assembled plan. We pass the loaded
    # donors dict directly so the script doesn't re-read the YAML.
    skill_bridge.install()
    import validate_plan as vp  # vendored
    from graph import donor_map  # noqa: WPS433
    donors = donor_map._load()  # noqa: SLF001 — internal cache reuse

    blockers: list[str] = []
    warnings: list[str] = []
    checklist: dict[str, Any] = {}

    # validate_plan emits "auto-added canonical color=..." every time a slot
    # lacks an explicit colour and build_v9 backfills it with the brand
    # default — i.e. on every well-formed slide. These messages are
    # informational, not actionable, and inflate the warning count (11/21
    # warnings on the 2026-06-04 live run were of this shape, dragging the
    # verifier score down). Keep them in ``checklist`` for the UI summary
    # but drop them from the deck-level warnings roll-up.
    def _is_noise(msg: str) -> bool:
        return "auto-added canonical" in msg or "применено canonical правило" in msg

    plan_slides = plan.get("slides") or []
    for idx, slide in enumerate(plan_slides, start=1):
        _, errs, warns = vp.validate_slide(idx, slide, donors)
        checklist[str(idx)] = {
            "checks_passed": int(not errs),
            "issues": [*errs, *warns],
        }
        blockers.extend(f"slide {idx}: {e}" for e in errs)
        warnings.extend(
            f"slide {idx}: {w}" for w in warns if not _is_noise(w)
        )

    # 2. Roll in Brand Guardian fails as blockers.
    brand_verdict = brand.get("verdict", "WARN")
    if brand_verdict == "FAIL":
        for sb in brand.get("slides", []) or []:
            if sb.get("verdict") == "FAIL":
                num = sb.get("slide_num")
                for v in sb.get("violations") or []:
                    if v.get("severity") == "FAIL":
                        blockers.append(f"brand slide {num}: {v.get('rule')} — {v.get('msg')}")

    # 3. Visual Verifier rejects.
    visual_verdict = visual.get("llm_verdict", "READY")
    for sv in visual.get("slides", []) or []:
        sv_v = sv.get("slide_verdict")
        if sv_v in ("REJECT", "NEEDS_REWORK"):
            num = sv.get("num")
            for iss in sv.get("issues") or []:
                sev = iss.get("severity")
                tag = f"visual slide {num}: {iss.get('rule')} — {iss.get('msg')}"
                (blockers if sev == "FAIL" else warnings).append(tag)

    deck_verdict = "NEEDS_REWORK" if (
        blockers or brand_verdict == "FAIL" or visual_verdict == "NEEDS_REWORK"
    ) else "READY"

    # Score: prefer visual score (rubric-based), fall back to brand score.
    score_avg = int(visual.get("score_avg") or brand.get("score_avg") or 0)

    verdict = VerifierVerdict(
        verdict=deck_verdict,
        score_avg=score_avg,
        checklist_results=checklist,
        blockers=blockers,
        warnings=warnings,
        next_actions=list(visual.get("next_actions") or []),
    )
    arts["verifier_verdict"] = verdict.model_dump()
    logger.info(
        "node.process_verify.done",
        session_id=state.session_id,
        verdict=deck_verdict,
        blockers=len(blockers),
        warnings=len(warnings),
        score=score_avg,
    )
    return {
        "artefacts": arts,
        "stage": Stage.VALIDATING.value,
        "progress_pct": 96,
    }


# ─── finalize_node — terminal ────────────────────────────────────────────────

def finalize_node(state: SessionState) -> dict[str, Any]:
    """Publish the terminal progress event with the built .pptx path so the
    bot side can send the result to the user.

    M3 interim: ``result_path`` is a local filesystem path (worker and bot
    share the same machine). M5 will swap this for an S3 key without
    changing the field name.
    """
    arts = _artefacts(state)
    verdict = arts.get("verifier_verdict", {}).get("verdict", "NEEDS_REWORK")
    built_path = arts.get("built_pptx_path") or state.result_s3_key
    notes = list(state.notes)

    if verdict == "READY":
        notes.append("Готово")
    elif verdict == "NEEDS_REWORK":
        # Build still produced a .pptx — bot can deliver it with a caveat.
        notes.append("Готов черновик, но верификатор просит доработку.")

    progress.done(
        state.session_id,
        detail="готово" if verdict == "READY" else "draft",
        result_path=built_path,
    )
    logger.info("node.finalize.done", session_id=state.session_id,
                verdict=verdict, has_built=bool(built_path))
    return {
        "stage": Stage.DONE.value,
        "progress_pct": 100,
        "notes": notes,
        "artefacts": arts,
    }
