"""LLM-agent nodes for the v0.9 batch pipeline.

Each function is a LangGraph node:
    (state: SessionState) -> dict (state patch)

All nodes read upstream artefacts from ``state.artefacts`` and write their
own output back into the same dict. The reducer is shallow-merge by
LangGraph; we copy + update + return the whole ``artefacts`` dict to avoid
clobbering sibling keys.

Vision-capable nodes (Brief Reader, Visual Verifier) accept rendered PNGs.
Brief Reader runs vision-grounded if ``parsed_deck`` includes an
``original_pngs`` key with a list of base64 data URLs or paths; otherwise
falls back to text-only (still on Kimi — accuracy boost from grounding is
nice-to-have, not required).
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from llm.output_parsers import call_and_parse
from llm.prompts import (
    agent_01_brief_reader,
    agent_02_slide_classifier,
    agent_03_content_distributor,
    agent_04_layout_designer,
    agent_05_icon_picker,
    agent_06_infographic_maker,
    agent_07_copy_editor,
    agent_10_visual_verifier,
)
from llm.roles import Role
from schemas.session import SessionState, Stage
from schemas.slides import (
    Brief,
    ContentAssignment,
    DeckClassification,
    IconAssignments,
    InfographicSpec,
    LayoutPlan,
    VisualVerdict,
)
from worker import progress

logger = structlog.get_logger(__name__)


# ─── shared helpers ──────────────────────────────────────────────────────────

def _artefacts(state: SessionState) -> dict[str, Any]:
    """Shallow copy of state.artefacts so we can mutate-and-return safely."""
    return dict(state.artefacts)


def _emit(state: SessionState, stage: Stage, pct: int, detail: str) -> None:
    progress.stage(state.session_id, stage, pct=pct, detail=detail)


# ─── 01 Brief Reader (Kimi vision) ───────────────────────────────────────────

def brief_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.PARSING, pct=15, detail="чтение брифа")
    arts = _artefacts(state)
    parsed_deck = arts.get("parsed_deck")
    if parsed_deck is None:
        raise RuntimeError("brief_node: artefacts['parsed_deck'] missing — parse_node didn't run")

    # Optional vision grounding: orchestrator stores rendered PNGs under
    # 'original_pngs' (list of bytes / data-URLs). Kimi vision tolerates empty.
    images = arts.get("original_pngs", [])

    messages, imgs = agent_01_brief_reader.build_messages(parsed_deck, images=images)
    # Brief Reader uses Kimi vision (requires_vision=True). If no PNGs were
    # rendered (text-only draft like .md), inject a 1×1 placeholder PNG so
    # the vision gate in call_role doesn't fire. FIXME: render first slide
    # of input pptx to PNG in parse_node — better grounding than placeholder.
    if not imgs:
        # 1×1 transparent PNG (base64). Keeps Kimi happy without misleading.
        imgs = [
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        ]

    brief, _ = call_and_parse(
        role=Role.BRIEF_PARSER,
        messages=messages,
        model_cls=Brief,
        images=imgs,
    )
    arts["brief"] = brief.model_dump()
    logger.info("node.brief.done", session_id=state.session_id,
                slide_count=brief.slide_count, topic=brief.topic[:60])
    return {"artefacts": arts, "stage": Stage.PARSING.value, "progress_pct": 20}


# ─── 02 Slide Classifier (DeepSeek) ──────────────────────────────────────────

def _coerce_thin_tables(classification_dump: dict[str, Any]) -> int:
    """Demote ``table_native`` slides with <3 columns to ``multicolumn``.

    The classifier prompt says "Регулярная таблица ≥3×3 → table_native" but
    the LLM occasionally picks ``table_native`` on 2-column lists. Canonical
    triggers (in ``validate_plan.py``) then flag it as a layout mistake.
    Coerce here so downstream nodes get a sensible donor.

    Mutates in place. Returns the count of coerced slides.
    """
    coerced = 0
    for s in classification_dump.get("slides") or []:
        if s.get("slide_type") != "table_native":
            continue
        tbl = s.get("table") or {}
        n_cols = len(tbl.get("headers") or [])
        if n_cols >= 3:
            continue
        # 2-col table → multicolumn with 2col hint; 0/1-col → text.
        s["slide_type"] = None
        s["table"] = None
        if n_cols == 2:
            s["category"] = "multicolumn"
            s["subcategory_hint"] = "2col"
        else:
            s["category"] = "text"
        coerced += 1
    return coerced


def _coerce_overflow_kpis(classification_dump: dict[str, Any]) -> int:
    """Clamp ``kpi_native`` slides to the renderer's hard 1-3 numbers limit.

    ``skill_assets/scripts/kpi_renderer.py::render_kpi`` raises
    ``ValueError("KPI supports 1-3 numbers, got N")`` for n==0 or n>3.
    Classifier prompt asks for "3 ключевых KPI" but the LLM occasionally
    produces 4-6 (it concatenates every number in the brief) or 0
    (mis-classifies a non-stats slide as ``kpi_native``).

    Policy:
      • n > 3 → truncate to first 3. Preserves the KPI layout, which is
        the strongest visual element on a stats slide; the LLM puts the
        most salient numbers first, so the tail is the safer cut.
      • n == 0 → demote to ``multicolumn``. A KPI slide with no numbers
        is broken; multicolumn is a safe text-only fallback.

    Mutates in place. Returns the count of slides touched.
    """
    coerced = 0
    for s in classification_dump.get("slides") or []:
        if s.get("slide_type") != "kpi_native":
            continue
        kpi = s.get("kpi") or {}
        nums = kpi.get("numbers") or []
        if 1 <= len(nums) <= 3:
            continue
        if len(nums) > 3:
            kpi["numbers"] = nums[:3]
            s["kpi"] = kpi
        else:  # len(nums) == 0
            s["slide_type"] = None
            s["kpi"] = None
            s["category"] = "multicolumn"
        coerced += 1
    return coerced


def _inject_parsed_tables(
    classification_dump: dict[str, Any],
    parsed_deck: dict[str, Any],
) -> int:
    """Force ``table_native`` with REAL cell data for slides whose source
    .pptx slide held a regular table.

    ``parse_pptx`` extracts the table grid, but the LLM brief→classify chain
    loses the cell text: Kimi marks ``intent=table`` with empty ``raw_body``,
    so the classifier defaults to ``category=text`` with no ``table`` block.
    Build then falls back to the donor-53 PNG-stub placeholder
    ("Столбец 1…/Строка 1…/+" — live dl1 slide 4 "DNS Resolvers"). Here we
    deterministically restore the table from the parsed grid so
    ``table_renderer`` draws the actual branded zebra table.

    Only regular tables (≥3 cols, uniform width, no merged cells) are
    injected; irregular/merged tables are left to the LLM (anti-distortion).
    Native types the classifier deliberately chose (kpi/chart/flow/image) and
    split parts are never overridden.

    Mutates in place. Returns the count of slides injected.
    """
    parsed_by_num: dict[int, dict[str, Any]] = {}
    for ps in (parsed_deck.get("slides") or []):
        n = ps.get("num")
        if not isinstance(n, int):
            continue
        tbls = [
            t for t in (ps.get("tables") or [])
            if t.get("regular") and len(t.get("headers") or []) >= 3
        ]
        if tbls:
            parsed_by_num[n] = {"grid": tbls[0], "title": ps.get("title") or ""}
    if not parsed_by_num:
        return 0

    injected = 0
    for s in classification_dump.get("slides") or []:
        src = s.get("_source_slide") or s.get("num")
        if not isinstance(src, int):
            continue
        entry = parsed_by_num.get(src)
        if not entry:
            continue
        if s.get("slide_type") in (
            "kpi_native", "chart_pptx_native",
            "flow_diagram_native", "image_native",
        ):
            continue
        if s.get("_split_part"):
            continue
        grid = entry["grid"]
        headers = [str(h) for h in (grid.get("headers") or [])]
        rows = [[str(c) for c in r] for r in (grid.get("rows") or [])]
        if not headers or not rows:
            continue
        prev = s.get("table") if isinstance(s.get("table"), dict) else {}
        header_txt = (prev.get("header") or entry["title"] or "").strip()
        s["slide_type"] = "table_native"
        s["category"] = "table"
        s["table"] = {
            "header": header_txt,
            "subtitle": prev.get("subtitle", ""),
            "style": "zebra",
            "headers": headers,
            "data": rows,
            "first_col_wider": True,
        }
        injected += 1
    return injected


def classify_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.CLASSIFYING, pct=25, detail="классификация слайдов")
    arts = _artefacts(state)
    brief = arts["brief"]

    classification, _ = call_and_parse(
        role=Role.CLASSIFIER,
        messages=agent_02_slide_classifier.build_messages(brief),
        model_cls=DeckClassification,
    )
    classification_dump = classification.model_dump()
    thin_tables = _coerce_thin_tables(classification_dump)
    overflow_kpis = _coerce_overflow_kpis(classification_dump)
    injected_tables = _inject_parsed_tables(
        classification_dump, arts.get("parsed_deck") or {})
    arts["classification"] = classification_dump
    if injected_tables:
        logger.info(
            "node.classify.parsed_tables_injected",
            session_id=state.session_id,
            count=injected_tables,
        )
    if thin_tables:
        logger.warning(
            "node.classify.thin_tables_coerced",
            session_id=state.session_id,
            count=thin_tables,
        )
    if overflow_kpis:
        logger.warning(
            "node.classify.overflow_kpis_coerced",
            session_id=state.session_id,
            count=overflow_kpis,
        )
    logger.info("node.classify.done", session_id=state.session_id,
                slides=len(classification.slides),
                thin_tables_coerced=thin_tables,
                overflow_kpis_coerced=overflow_kpis,
                parsed_tables_injected=injected_tables)
    return {"artefacts": arts, "stage": Stage.CLASSIFYING.value, "progress_pct": 30}


# ─── 04 Layout Designer (DeepSeek) ───────────────────────────────────────────

def design_node(state: SessionState) -> dict[str, Any]:
    """Runs Agent 04 BEFORE Distributor — Distributor needs slot capacities
    from the chosen donors. Order: classify → design → distribute.

    Post-LLM, validates every ``layout_idx`` against
    ``donor_map.valid_donor_ids()``. Picks that aren't in the slot map
    (designer hallucination — common before v1.1 prompt rewrite, e.g.
    template meta-slides 1, 9) are replaced by
    ``default_donor_for_category()``. We DON'T re-run the LLM on bad
    picks — a deterministic fallback keeps the cost predictable.
    Native slides (layout_idx=0) are passed through.
    """
    _emit(state, Stage.DESIGNING, pct=35, detail="подбор layout")
    arts = _artefacts(state)
    classification = arts["classification"]

    layouts, _ = call_and_parse(
        role=Role.DESIGNER,
        messages=agent_04_layout_designer.build_messages(classification),
        model_cls=LayoutPlan,
    )

    from graph import donor_map  # noqa: WPS433 — local to keep cycle clear
    valid = donor_map.valid_donor_ids()
    cls_by_num: dict[int, dict[str, Any]] = {
        int(s.get("num", 0)): s for s in (classification.get("slides") or [])
    }

    layouts_dump = layouts.model_dump(by_alias=True)
    repairs: list[dict[str, Any]] = []
    for entry in layouts_dump.get("slides") or []:
        idx = entry.get("layout_idx")
        if idx in (None, 0):
            # 0 = native render (no donor) — leave alone.
            continue
        if int(idx) in valid:
            continue
        cls = cls_by_num.get(int(entry.get("num") or 0)) or {}
        fallback = donor_map.default_donor_for_category(
            cls.get("category", "other"),
            subcategory_hint=cls.get("subcategory_hint"),
            dark=bool(cls.get("dark")),
        )
        repairs.append({
            "num": entry.get("num"),
            "from": idx,
            "to": fallback,
            "category": cls.get("category"),
        })
        # Fallback to None means we couldn't find a safe donor — keep the
        # LLM's pick so the pipeline still produces something; assemble_node
        # will log the unmapped donor when it tries to translate slots.
        entry["layout_idx"] = fallback if fallback is not None else idx
        entry["layout_name"] = entry.get("layout_name") or "fallback"
        entry["rationale"] = (entry.get("rationale") or "") + " [auto-repair: donor not in slot map]"

    if repairs:
        logger.warning(
            "node.design.invalid_donors_repaired",
            session_id=state.session_id,
            count=len(repairs),
            repairs=repairs,
        )

    arts["layouts"] = layouts_dump
    logger.info("node.design.done", session_id=state.session_id,
                slides=len(layouts_dump.get("slides") or []),
                repaired=len(repairs))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 40}


# ─── 03 Content Distributor (GLM OFF) ────────────────────────────────────────

def distribute_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=45, detail="распределение контента")
    arts = _artefacts(state)
    brief = arts["brief"]
    classification = arts["classification"]
    layouts = arts["layouts"]
    # Pull per-donor slot capacities from skill_assets/brand/donor-slot-map.yaml
    # so GLM can fit copy to safe_max_chars. Native slides (layout_idx=0) are
    # skipped — they don't have a donor and the distributor ignores them.
    from graph import donor_map  # noqa: WPS433 — local import keeps cycle clear
    layout_idxs = [
        s.get("layout_idx") or s.get("donor") or 0
        for s in (layouts.get("slides") or [])
    ]
    slot_specs = donor_map.slot_specs_for_layouts(layout_idxs)

    content, _ = call_and_parse(
        role=Role.DISTRIBUTOR,
        messages=agent_03_content_distributor.build_messages(
            brief, classification, layouts, slot_specs,
        ),
        model_cls=_DeckContentAssignment,
    )
    arts["content"] = content.model_dump()
    logger.info("node.distribute.done", session_id=state.session_id,
                slides=len(content.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 50}


# Distributor outputs a deck-level wrapper {"slides": [ContentAssignment, ...]}.
# schemas/slides.py defines ContentAssignment per-slide; declare the wrapper
# locally so we don't pollute the public schema module.
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402 — co-located helper


class _DeckContentAssignment(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[ContentAssignment] = Field(default_factory=list)


class _DeckIcons(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[IconAssignments] = Field(default_factory=list)


class _DeckInfographics(BaseModel):
    model_config = ConfigDict(extra="allow")
    slides: list[InfographicSpec] = Field(default_factory=list)


# ─── 05 Icon Picker (GLM OFF) ────────────────────────────────────────────────

def icons_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=55, detail="подбор иконок")
    arts = _artefacts(state)
    # Scan vendored SVGs. Currently only brand_arrow.svg ships with M2;
    # Icon Picker will return fallback=TODO for most blocks until the
    # library is populated (tracked outside M3).
    from worker.skill_bridge import SKILL_BRAND  # noqa: WPS433
    icons_dir = SKILL_BRAND / "icons"
    icon_library = sorted(
        f"icons/{p.name}" for p in icons_dir.glob("*.svg")
    ) if icons_dir.is_dir() else []

    icons, _ = call_and_parse(
        role=Role.ICON_PICKER,
        messages=agent_05_icon_picker.build_messages(
            arts["classification"], arts["content"], icon_library,
        ),
        model_cls=_DeckIcons,
    )
    arts["icons"] = icons.model_dump()
    logger.info("node.icons.done", session_id=state.session_id,
                slides=len(icons.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 60}


# ─── 06 Infographic Maker (GLM OFF) ──────────────────────────────────────────

def infographic_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=65, detail="инфографика")
    arts = _artefacts(state)
    infographics, _ = call_and_parse(
        role=Role.INFOGRAPHIC_MAKER,
        messages=agent_06_infographic_maker.build_messages(
            arts["classification"], arts["content"],
        ),
        model_cls=_DeckInfographics,
    )
    arts["infographics"] = infographics.model_dump()
    logger.info("node.infographic.done", session_id=state.session_id,
                slides=len(infographics.slides))
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 70}


# ─── 07 Copy Editor (GLM OFF) ────────────────────────────────────────────────

# Emoji codepoints render as empty squares (□) under SB Sans Display (the
# Cloud.ru template font). Visual Verifier flagged this on slide 4 of the
# 2026-06-04 live run ("эмодзи отображаются как пустые квадраты"). Source
# decks routinely use emoji as bullet markers (📤🔗📊🧠) which the LLM
# happily passes through. Strip them deterministically post-copyedit so we
# don't depend on the LLM remembering to clean them up.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs, transport, emoticons, supplemental
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicator (flags)
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0001F000-\U0001F02F"  # mahjong/dominos
    "\U0001F0A0-\U0001F0FF"  # playing cards
    "]",
    flags=re.UNICODE,
)


def _strip_unsupported_glyphs(text: str) -> str:
    """Remove emoji codepoints and collapse any whitespace they leave behind.

    Returns the input unchanged when there are no matches so we don't churn
    well-formed strings.
    """
    if not text or not _EMOJI_PATTERN.search(text):
        return text
    cleaned = _EMOJI_PATTERN.sub("", text)
    # Tidy up leftover double spaces / leading bullets without an icon.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]+", "", cleaned)
    return cleaned.strip()


def _strip_emoji_from_content(content_dump: dict[str, Any]) -> int:
    """Apply ``_strip_unsupported_glyphs`` to every placeholder content in a
    DeckContentAssignment dump. Returns the number of fields that changed.

    Mutates the dict in place.
    """
    changed = 0
    for slide in content_dump.get("slides") or []:
        for ph in slide.get("placeholder_assignments") or []:
            orig = ph.get("content")
            if isinstance(orig, str):
                new = _strip_unsupported_glyphs(orig)
                if new != orig:
                    ph["content"] = new
                    changed += 1
    return changed


def copyedit_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.DESIGNING, pct=72, detail="редактура текста")
    arts = _artefacts(state)
    edited, _ = call_and_parse(
        role=Role.COPY_EDITOR,
        messages=agent_07_copy_editor.build_messages(arts["content"]),
        model_cls=_DeckContentAssignment,
    )
    edited_dump = edited.model_dump()
    emoji_stripped = _strip_emoji_from_content(edited_dump)
    arts["copy_edited"] = edited_dump
    total_edits = sum(s.edits_count for s in edited.slides)
    logger.info("node.copyedit.done", session_id=state.session_id,
                slides=len(edited.slides), edits=total_edits,
                emoji_stripped=emoji_stripped)
    return {"artefacts": arts, "stage": Stage.DESIGNING.value, "progress_pct": 75}


# ─── 10 Visual Verifier (Kimi vision) ────────────────────────────────────────

def visual_verify_node(state: SessionState) -> dict[str, Any]:
    _emit(state, Stage.VALIDATING, pct=90, detail="визуальная проверка")
    arts = _artefacts(state)
    plan = arts.get("plan")
    if plan is None:
        raise RuntimeError("visual_verify_node: artefacts['plan'] missing — assemble_plan_node didn't run")
    rendered_pngs = arts.get("rendered_pngs", [])
    if not rendered_pngs:
        # FIXME(next-chunk): render_png_node must populate this. For now
        # skip with a NEEDS_REWORK verdict so we don't silently pass.
        logger.warning("node.visual.skip_no_pngs", session_id=state.session_id)
        arts["visual_verdict"] = {
            "llm_verdict": "NEEDS_REWORK",
            "score_avg": 0,
            "slides": [],
            "next_actions": ["render_png_node not yet implemented — cannot verify"],
        }
        return {"artefacts": arts, "stage": Stage.VALIDATING.value, "progress_pct": 92}

    messages, imgs = agent_10_visual_verifier.build_messages(plan, rendered_pngs)
    verdict, _ = call_and_parse(
        role=Role.VISUAL_VERIFIER,
        messages=messages,
        model_cls=VisualVerdict,
        images=imgs,
    )
    arts["visual_verdict"] = verdict.model_dump()
    logger.info("node.visual.done", session_id=state.session_id,
                verdict=verdict.llm_verdict, score=verdict.score_avg)
    return {"artefacts": arts, "stage": Stage.VALIDATING.value, "progress_pct": 92}


# ─── M4 Autofix loop ─────────────────────────────────────────────────────────

AUTOFIX_BUDGET = 1
"""Max number of autofix passes per session. Each pass is a full re-build +
re-verify cycle, so the wall-clock cost is roughly equal to one nominal
pipeline run. We cap at 1 to keep per-deck Cloud.ru spend predictable; raise
only after measuring real lift from a second pass."""


# Categories of issues for autofix routing — see T1.1 diagnosis 2026-06-04
# (memory/live_run_findings.md). Live run had 8/11 blockers in text_replaced
# + semantics (caused by ph_type bug, fixed in T0.2) — the autofix loop wasted
# a retry on COPY_EDITOR which couldn't address them. These tags let
# autofix_can_help() skip when COPY_EDITOR would be ineffective.
_ISSUE_CATEGORIES = (
    "text_overflow",   # chars > max — COPY_EDITOR can rephrase/shorten
    "text_replaced",   # placeholder leaked into render — needs build/donor fix
    "semantics",       # content doesn't match slide topic — COPY_EDITOR may help
    "aesthetic",       # missing brand accents / scannability — needs visual agent
    "other",
)
# Substrings (lowercased) that map an issue line to a category.
_TAG_BY_SUBSTRING: tuple[tuple[str, str], ...] = (
    ("text_replaced", "text_replaced"),
    ("placeholder", "text_replaced"),
    ("overflow", "text_overflow"),
    ("chars > max", "text_overflow"),
    ("strategy 3", "text_overflow"),
    ("semantics_ok", "semantics"),
    ("не соответствует", "semantics"),
    ("hierarchy", "aesthetic"),
    ("philosophy", "aesthetic"),
    ("function", "aesthetic"),
    ("detail", "aesthetic"),
    ("бренд", "aesthetic"),
    ("сканируется", "aesthetic"),
)


def _categorize_issue(line: str) -> str:
    s = line.lower()
    for needle, tag in _TAG_BY_SUBSTRING:
        if needle in s:
            return tag
    return "other"


def issue_breakdown(arts: dict[str, Any]) -> dict[str, int]:
    """Count blockers + warnings by category. Used by route guards + logs."""
    counts: dict[str, int] = {c: 0 for c in _ISSUE_CATEGORIES}
    ver = arts.get("verifier_verdict") or {}
    for item in (ver.get("blockers") or []) + (ver.get("warnings") or []):
        text = item if isinstance(item, str) else \
               (item.get("msg") or item.get("text") or str(item))
        counts[_categorize_issue(str(text))] += 1
    return counts


_AUTOFIX_SCORE_FLOOR = 60
"""Verdict scores >= this number are considered shippable as-is — autofix
risks regressing other slides for marginal gain. Empirical: 2026-06-05 run
went from score=61 (after first build) to 43 after autofix retry, because
COPY_EDITOR touches every slide and breaks aesthetic balance on those
that weren't the target."""


def autofix_can_help(arts: dict[str, Any]) -> bool:
    """True iff autofix retry is likely to improve the verdict.

    COPY_EDITOR fixes ``text_overflow`` (shorten) and ``semantics``
    (rephrase to match topic). ``text_replaced`` (placeholder leak — build
    bug) and ``aesthetic`` (needs INFOGRAPHIC_MAKER) are out of scope.

    Three gates compose (all must pass to enter autofix):
      1. score < _AUTOFIX_SCORE_FLOOR — verdict is bad enough that the
         risk of regressing other slides is worth taking.
      2. at least one fixable category (text_overflow + semantics > 0).
      3. fixable categories are not dominated by unfixable ones — if
         aesthetic/text_replaced/other outnumber fixable 2:1, the
         feedback list is mostly noise to COPY_EDITOR and the retry
         tends to over-edit (2026-06-05 run regressed 11→13 warnings).
    """
    ver = arts.get("verifier_verdict") or {}
    score = int(ver.get("score_avg") or 0)
    if score >= _AUTOFIX_SCORE_FLOOR:
        return False
    b = issue_breakdown(arts)
    fixable = b["text_overflow"] + b["semantics"]
    if fixable == 0:
        return False
    unfixable = b["text_replaced"] + b["aesthetic"] + b["other"]
    if unfixable > 2 * fixable:
        return False
    return True


def _collect_verifier_feedback(arts: dict[str, Any]) -> list[str]:
    """Extract per-slide actionable issues for the autofix prompt.

    Pulls from ``verifier_verdict.warnings`` (already filtered for canonical
    noise in ``process_verify_node``) and ``visual_verdict.slides[].issues``
    so the copy editor sees both validate_plan-level and vision-level signal.
    """
    feedback: list[str] = []
    ver = arts.get("verifier_verdict") or {}
    for b in (ver.get("blockers") or []):
        feedback.append(f"BLOCKER: {b}")
    for w in (ver.get("warnings") or []):
        feedback.append(f"WARN: {w}")
    vis = arts.get("visual_verdict") or {}
    for sv in (vis.get("slides") or []):
        if sv.get("slide_verdict") in ("REJECT", "NEEDS_REWORK"):
            num = sv.get("num")
            for iss in (sv.get("issues") or []):
                rule = iss.get("rule") or ""
                msg = (iss.get("msg") or "")[:200]
                feedback.append(f"slide {num} ({rule}): {msg}")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for line in feedback:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def autofix_node(state: SessionState) -> dict[str, Any]:
    """Single autofix pass.

    Reads verifier feedback, re-runs Agent 07 (Copy Editor) with the
    feedback baked into the user message, and re-strips emoji. The graph
    loops back to ``assemble_plan`` so build / brand / render / visual /
    process_verify all re-run with the updated content.

    Deterministic-only mutations (overflow size_pt, table demotion) are
    handled upstream in ``classify_node`` and ``design_node``; this node
    targets text-shaped issues that need LLM intervention.
    """
    arts = _artefacts(state)
    iteration = int(state.autofix_iterations or 0) + 1
    _emit(state, Stage.VALIDATING, pct=95,
          detail=f"автоисправление #{iteration}")

    feedback = _collect_verifier_feedback(arts)
    base_content = arts.get("copy_edited") or arts.get("content") or {}

    # Build the copy-editor prompt and append verifier feedback so the LLM
    # knows what to focus on. Keep the original SYSTEM rules intact — we
    # don't want the editor to start rewriting semantics, just to address
    # the specific complaints. If the feedback list is empty we fall back
    # to a plain re-run (still helpful: occasionally Copy Editor catches
    # things it missed first time).
    msgs = agent_07_copy_editor.build_messages(base_content)
    if feedback:
        bullet_list = "\n".join(f"- {line}" for line in feedback[:30])
        msgs.append({
            "role": "user",
            "content": (
                "Верификатор нашёл проблемы. Исправь только их, остальное оставь:\n"
                f"{bullet_list}\n\n"
                "ОСОБОЕ ВНИМАНИЕ: эмодзи (📤🔗📊🧠 и т.п.) в шрифте Cloud.ru "
                "отображаются как пустые квадраты — удаляй их полностью. "
                "Длинные строки сокращай, не теряя смысла."
            ),
        })

    edited, _ = call_and_parse(
        role=Role.COPY_EDITOR,
        messages=msgs,
        model_cls=_DeckContentAssignment,
    )
    edited_dump = edited.model_dump()
    emoji_stripped = _strip_emoji_from_content(edited_dump)
    arts["copy_edited"] = edited_dump

    logger.info(
        "node.autofix.done",
        session_id=state.session_id,
        iteration=iteration,
        feedback_items=len(feedback),
        emoji_stripped=emoji_stripped,
        slides=len(edited.slides),
        breakdown=issue_breakdown(arts),
    )
    return {
        "artefacts": arts,
        "stage": Stage.VALIDATING.value,
        "progress_pct": 78,  # rewind progress to indicate the loop-back
        "autofix_iterations": iteration,
    }
