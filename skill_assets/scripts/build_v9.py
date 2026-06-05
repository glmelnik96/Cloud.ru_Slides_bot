#!/usr/bin/env python3
"""
build_v7.py — build_v6 + поддержка ДУБЛЕЙ donor.

Ключевое улучшение vs v6:
- Если donor 13 нужен 3 раза → клонируется 3 раза (не один и не игнорируется)
- Через XML deepcopy slide part-а в presentation
- Сохраняет правильный порядок слайдов

Plan:
{
  "slides": [
    {"clone_from_slide": 13, "slots": {...}},
    {"clone_from_slide": 12, "slots": {...}},
    {"clone_from_slide": 13, "slots": {...}}  ← ДУБЛЬ donor 13!
  ]
}

Usage:
    python3 build_v7.py <plan.json> <template.pptx> <output.pptx> [donor-slot-map.yaml]
"""
import sys
import json
import os
import copy
from pptx import Presentation
from pptx.util import Emu
from pptx.oxml.ns import qn
from lxml import etree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_v5 import (
    load_donor_map, get_text_frame_by_shape_idx, replace_text_with_style,
    clear_text_frame
)
from kpi_renderer import (
    render_kpi, clean_slide_to_blank,
    BLANK_DONOR_WHITE, BLANK_DONOR_DARK
)
from image_renderer import render_image_native
try:
    from chart_engine import render_chart
    CHART_AVAILABLE = True
except ImportError:
    CHART_AVAILABLE = False

try:
    from chart_native_pptx import render_chart_pptx_slide
    CHART_NATIVE_PPTX_AVAILABLE = True
except ImportError:
    CHART_NATIVE_PPTX_AVAILABLE = False

try:
    from flow_renderer import render_flow_diagram_slide
    FLOW_RENDERER_AVAILABLE = True
except ImportError:
    FLOW_RENDERER_AVAILABLE = False

try:
    from table_renderer import render_table_native
    TABLE_RENDERER_AVAILABLE = True
except ImportError:
    TABLE_RENDERER_AVAILABLE = False

try:
    from infographic_renderer import (
        render_infographic_shapes,
        clear_donor_body_slots,
        clear_donor_non_title_text,
    )
    INFOGRAPHIC_RENDERER_AVAILABLE = True
except ImportError:
    INFOGRAPHIC_RENDERER_AVAILABLE = False

try:
    from bullet_splitter import split_slot_if_body
    BULLET_SPLITTER_AVAILABLE = True
except ImportError:
    BULLET_SPLITTER_AVAILABLE = False
    def split_slot_if_body(_name, text):  # noqa: D401 — no-op fallback
        return text

EMU_PER_PX = 9525


def clone_slide(prs, src_slide):
    """Глубоко копирует slide-part и регистрирует его в presentation.
    Возвращает новый Slide (последний в prs.slides)."""
    from pptx.opc.constants import CONTENT_TYPE as CT
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.opc.constants import RELATIONSHIP_TARGET_MODE as RTM
    from pptx.opc.packuri import PackURI
    from pptx.opc.package import _Relationship
    from pptx.parts.slide import SlidePart

    src_part = src_slide.part
    src_xml = src_part.blob

    # Подбираем уникальное имя slideN.xml
    package = prs.part.package
    existing_partnames = {str(p.partname) for p in package.iter_parts()}
    next_idx = 1
    while f"/ppt/slides/slide{next_idx}.xml" in existing_partnames:
        next_idx += 1
    new_partname = PackURI(f"/ppt/slides/slide{next_idx}.xml")

    # Создаём новый part — используем тот же content_type как у src
    new_part = SlidePart.load(
        partname=new_partname,
        content_type=src_part.content_type,
        blob=src_xml,
        package=package,
    )

    # Копируем relationships, СОХРАНЯЯ оригинальные rId (fix 2026-06-02).
    # Почему не relate_to: он ПЕРЕНУМЕРОВЫВАЕТ rId по порядку обхода, а XML слайда
    # (скопирован блобом) ссылается на ИСХОДНЫЕ rId. В итоге blip-картинка с
    # r:embed="rId3" начинала указывать на slideLayout вместо изображения →
    # PowerPoint «не смог прочитать часть содержимого» и удалял картинку.
    # Сохраняя rId, держим ссылки валидными. notesSlide-связь НЕ копируем: иначе
    # донорский notesSlide ссылается назад на ОРИГИНАЛ-слайд → тот остаётся
    # «сиротой» (в пакете, но не в sldIdLst) → PowerPoint repair. Без неё оригинал
    # недостижим и корректно отбрасывается при save. Заметки донора слайду не нужны.
    # (Зависит от внутренностей python-pptx 1.0.2: _rels / _Relationship.)
    dst_rels = new_part.rels
    for rel in src_part.rels.values():
        if rel.reltype == RT.NOTES_SLIDE:
            continue
        if rel.is_external:
            dst_rels._rels[rel.rId] = _Relationship(
                dst_rels._base_uri, rel.rId, rel.reltype,
                target_mode=RTM.EXTERNAL, target=rel.target_ref)
        else:
            dst_rels._rels[rel.rId] = _Relationship(
                dst_rels._base_uri, rel.rId, rel.reltype,
                target_mode=RTM.INTERNAL, target=rel.target_part)

    # Регистрируем slide в presentation через relationship
    rId = prs.part.relate_to(new_part, RT.SLIDE)

    # Добавляем sldId в sldIdLst
    sldIdLst = prs.slides._sldIdLst
    existing_ids = [int(el.attrib["id"]) for el in sldIdLst if "id" in el.attrib]
    next_id = max(existing_ids) + 1 if existing_ids else 256
    new_sldId = etree.SubElement(sldIdLst, qn("p:sldId"))
    new_sldId.set("id", str(next_id))
    new_sldId.set(qn("r:id"), rId)

    return prs.slides[-1]


def build(plan_path, template_path, output_path, donor_map_path):
    plan = json.load(open(plan_path, encoding="utf-8"))
    p = Presentation(template_path)
    donors = load_donor_map(donor_map_path)

    # === STEP 1: Собираем нужные donor_nums и клонируем все слайды plan-а ===
    # Сохраняем reference на оригинальные donor slides ДО любых модификаций
    original_slides = list(p.slides)
    donor_originals = {}  # {donor_num: original_slide}
    for ps in plan["slides"]:
        n = ps.get("clone_from_slide")
        if n and n not in donor_originals:
            if 1 <= n <= len(original_slides):
                donor_originals[n] = original_slides[n - 1]
            else:
                print(f"WARN: donor {n} вне диапазона (1..{len(original_slides)})", file=sys.stderr)

    # Клонируем КАЖДЫЙ слайд из plan (включая дубли) → новые slides в конце
    # Для slide_type=="kpi_native": используем blank donor (slide 30/22 шаблона)
    cloned_for_plan = []
    for ps in plan["slides"]:
        slide_type = ps.get("slide_type")
        if slide_type in ("kpi_native", "image_native", "chart_native", "chart_pptx_native", "flow_diagram_native", "table_native"):
            dark = ps.get("dark", False)
            blank_idx = (BLANK_DONOR_DARK if dark else BLANK_DONOR_WHITE)
            if 1 <= blank_idx <= len(original_slides):
                new_slide = clone_slide(p, original_slides[blank_idx - 1])
                cloned_for_plan.append(new_slide)
                continue
        n = ps.get("clone_from_slide")
        if not n or n not in donor_originals:
            cloned_for_plan.append(None)
            continue
        new_slide = clone_slide(p, donor_originals[n])
        cloned_for_plan.append(new_slide)

    # === STEP 2: Удаляем все ОРИГИНАЛЬНЫЕ слайды (101+ template слайдов), оставляем только клоны ===
    sldIdLst = p.slides._sldIdLst
    n_originals = len(original_slides)
    # Первые n_originals элементов — это оригиналы. Удаляем их.
    all_sldIds = list(sldIdLst)
    for sldId in all_sldIds[:n_originals]:
        rId = sldId.attrib[qn('r:id')]
        try:
            p.part.drop_rel(rId)
        except Exception:
            pass
        sldIdLst.remove(sldId)

    # === STEP 3: Заполняем text + pictures для каждого clone ===
    pictures_inserted = 0
    for plan_slide, actual in zip(plan["slides"], cloned_for_plan):
        if actual is None:
            continue

        # === NATIVE RENDERS: build shapes from scratch on clean canvas ===
        slide_type = plan_slide.get("slide_type")
        if slide_type == "kpi_native":
            kpi_config = plan_slide.get("kpi", {})
            dark = plan_slide.get("dark", False)
            clean_slide_to_blank(actual)
            render_kpi(actual, kpi_config, dark=dark)
            continue
        if slide_type == "image_native":
            image_config = plan_slide.get("image", {})
            dark = plan_slide.get("dark", False)
            clean_slide_to_blank(actual)
            render_image_native(actual, image_config, dark=dark)
            continue
        if slide_type == "chart_pptx_native":
            if not CHART_NATIVE_PPTX_AVAILABLE:
                print("WARN: chart_native_pptx модуль недоступен — chart_pptx_native пропущен",
                      file=sys.stderr)
                continue
            chart_config = plan_slide.get("chart", {})
            dark = plan_slide.get("dark", False)
            clean_slide_to_blank(actual)
            render_chart_pptx_slide(actual, chart_config, dark=dark)
            continue
        if slide_type == "flow_diagram_native":
            if not FLOW_RENDERER_AVAILABLE:
                print("WARN: flow_renderer модуль недоступен — flow_diagram_native пропущен",
                      file=sys.stderr)
                continue
            flow_config = plan_slide.get("flow", {})
            dark = plan_slide.get("dark", False)
            clean_slide_to_blank(actual)
            render_flow_diagram_slide(actual, flow_config, dark=dark)
            continue
        if slide_type == "table_native":
            if not TABLE_RENDERER_AVAILABLE:
                print("WARN: table_renderer модуль недоступен — table_native пропущен",
                      file=sys.stderr)
                continue
            table_config = plan_slide.get("table", {})
            dark = plan_slide.get("dark", False)
            clean_slide_to_blank(actual)
            render_table_native(actual, table_config, dark=dark)
            continue
        if slide_type == "chart_native":
            if not CHART_AVAILABLE:
                print("WARN: matplotlib не установлен — chart_native пропущен", file=sys.stderr)
                continue
            chart_config = plan_slide.get("chart", {})
            dark = plan_slide.get("dark", False)
            # Render chart to PNG
            chart_png = plan_slide.get("chart_output_png",
                                        f"pptx-skill/output/_chart_slide_{id(plan_slide)}.png")
            render_chart(chart_config, chart_png, dpi=150)
            # Pass to image_native renderer (wide_zone for charts)
            clean_slide_to_blank(actual)
            render_image_native(actual, {
                "title": chart_config.get("slide_title", chart_config.get("title", "")),
                "image_path": chart_png,
                "caption": chart_config.get("caption", "")
            }, dark=dark, wide_zone=True)
            continue

        src_num = plan_slide.get("clone_from_slide")
        if src_num is None:
            continue
        donor_def = donors.get(src_num)

        # === STEP 3a: PRE-CLEANUP (PNG-stripping) ===
        # Источники remove_idx:
        #   1. donor_def.remove_before_fill — всегда удалять
        #   2. plan_slide.remove_shapes — ad-hoc per slide
        #   3. donor_def.remove_if_not_used — удалять если slot пустой
        #      (формат: {slot_name: [shape_idx]} в slot.shape_idx_when_unused — упрощённо мапим)
        #   4. donor_def.remove_if_user_provides_table — удалять если plan имеет table_data
        if donor_def is not None:
            # P0-2 (2026-06-05): donor 53 / 54 mark their PNG-stub in
            # ``remove_before_fill`` so a generated table can take its
            # place. BUT when no table_data is supplied (Agent 03 didn't
            # produce one — live run4.slide4 "DNS Resolvers" was empty),
            # stripping the stub yields a blank slide. Keep the stub for
            # fixed_png_content donors when neither table nor infographic
            # is available — the placeholder PNG is preferable to nothing.
            base_remove = list(donor_def.get("remove_before_fill", []))
            dtype_pre = donor_def.get("donor_type")
            has_replacement = bool(
                plan_slide.get("table_data")
                or plan_slide.get("infographic")
            )
            if dtype_pre == "fixed_png_content" and not has_replacement:
                if base_remove:
                    print(
                        f"WARN: donor {src_num} fixed_png_content без "
                        f"table_data/infographic — оставляю PNG-stub "
                        f"(remove_before_fill={base_remove} suppressed)",
                        file=sys.stderr,
                    )
                base_remove = []
            remove_idx_list = base_remove
            remove_idx_list += list(plan_slide.get("remove_shapes", []))

            # remove_if_user_provides_table: например donor 53 имеет PNG-таблицу-заглушку
            if plan_slide.get("table_data"):
                remove_idx_list += list(donor_def.get("remove_if_user_provides_table", []))

            # remove_if_not_used: парсим формат {slot_name: shape_idx_to_strip}
            # Если slot не указан в plan_slide.slots — добавить shape_idx в remove
            remove_when_unused = donor_def.get("remove_if_not_used", {}) or {}
            slots_filled_now = plan_slide.get("slots", {}) or {}
            if isinstance(remove_when_unused, dict):
                for slot_name, idx_to_strip in remove_when_unused.items():
                    if slot_name not in slots_filled_now:
                        if isinstance(idx_to_strip, list):
                            remove_idx_list += idx_to_strip
                        else:
                            remove_idx_list.append(idx_to_strip)

            # WARN если donor_type=fixed_png_content и нет ни remove_before_fill, ни overrides
            dtype = donor_def.get("donor_type")
            if dtype == "fixed_png_content" and not remove_idx_list:
                print(
                    f"WARN: donor {src_num} is 'fixed_png_content' но без remove_before_fill — "
                    f"PNG-заглушка может перекрыть контент",
                    file=sys.stderr,
                )

            if remove_idx_list:
                spTree = actual.shapes._spTree
                shape_elements = list(spTree)
                content_tags = ('sp', 'pic', 'grpSp', 'graphicFrame', 'cxnSp')
                content_shapes = [el for el in shape_elements
                                  if el.tag.split('}')[-1] in content_tags]
                for idx in sorted(set(remove_idx_list), reverse=True):
                    if 0 <= idx < len(content_shapes):
                        spTree.remove(content_shapes[idx])

        # TEXT slots
        if donor_def is not None:
            slot_defs = donor_def.get("slots", {})
            slots_filled = plan_slide.get("slots", {})
            styles_override = plan_slide.get("slot_styles_override", {})

            for slot_name, new_text in slots_filled.items():
                if slot_name not in slot_defs:
                    print(f"WARN: slot '{slot_name}' undefined for donor {src_num}", file=sys.stderr)
                    continue
                slot_cfg = slot_defs[slot_name]
                shape_idx = slot_cfg["shape_idx"]
                tf = get_text_frame_by_shape_idx(actual, shape_idx)
                if tf is None:
                    continue
                # D7 fix (2026-06-05): wall-of-text safety net. If a body
                # slot landed with a single 300+-char paragraph (distributor
                # didn't split), break at sentence boundaries so the donor's
                # bullet styling actually renders it as a list.
                if isinstance(new_text, str):
                    new_text = split_slot_if_body(slot_name, new_text)
                override = styles_override.get(slot_name)
                # D9 fix (2026-06-05): cover title overflow. When the text
                # noticeably exceeds the slot's safe_max_chars, proactively
                # shrink the font size so it fits — donor 4 title (60pt,
                # safe_max_chars=55) overflowed when the brief topic was
                # 70+ chars. We avoid relying on renderer-side shrink-to-fit
                # (normAutofit) because LibreOffice's autofit support is
                # inconsistent across versions used by render_png.
                txt_str = str(new_text or "")
                safe_max = slot_cfg.get("safe_max_chars") or slot_cfg.get("max_chars")
                base_size = (override or {}).get("size_pt") or slot_cfg.get("size_pt")
                if (safe_max and base_size and txt_str
                        and len(txt_str) > int(safe_max)):
                    # Linear shrink with 0.70 floor (below that titles become
                    # unreadable; better to let it clip than render at 8pt).
                    scale = max(0.70, float(safe_max) / float(len(txt_str)))
                    shrunk_pt = max(14, int(round(float(base_size) * scale)))
                    if shrunk_pt < int(base_size):
                        override = dict(override or {})
                        override["size_pt"] = shrunk_pt
                        print(
                            f"autofit: slot={slot_name} donor={src_num} "
                            f"len={len(txt_str)} safe_max={safe_max} "
                            f"size_pt {base_size}→{shrunk_pt}",
                            file=sys.stderr,
                        )
                replace_text_with_style(tf, new_text, override)

            # Очистить незаполненные обязательные слоты
            for slot_name, slot_def in slot_defs.items():
                if slot_name in slots_filled:
                    continue
                if slot_def.get("optional"):
                    continue
                shape_idx = slot_def["shape_idx"]
                tf = get_text_frame_by_shape_idx(actual, shape_idx)
                if tf is not None:
                    clear_text_frame(tf)

        # INFOGRAPHIC native_block (Agent 06): инжектим shape-список (rounded_rect+text)
        # с абсолютным позиционированием поверх клона донора. Когда инфографика
        # есть, body-слоты донора чистим — иначе старый шаблонный текст
        # «просвечивает» между блоками сравнения. Title остаётся (он не
        # дублируется в shape-списке инфографикa).
        info_block = plan_slide.get("infographic") or {}
        info_shapes = info_block.get("shapes") or []
        info_type = (info_block.get("type") or "").lower()
        # B5 (2026-06-05): live a337cc86 slide 12 showed donor 34's three
        # native columns AND Agent 06's 9-shape matrix rendered together.
        # If the donor itself IS a structural multicolumn/matrix layout,
        # the donor's slots already cover the same visual job — skip the
        # Agent 06 overlay entirely so we don't double-render.
        donor_cat = (donor_def.get("category") or "").lower() if donor_def else ""
        _STRUCTURAL_DONOR_CATS = (
            "content_2col", "content_3col_subtitle", "content_4subtitles",
            "content_6subtitles", "content_8subtitles", "content_4block",
        )
        _OVERLAY_TYPES = ("comparison", "matrix", "process", "flow", "tree")
        donor_already_structural = (
            donor_cat in _STRUCTURAL_DONOR_CATS and info_type in _OVERLAY_TYPES
        )

        # F1+F2 (2026-06-05): post-run7 visual review (eb6c4ceec3024bd9)
        # showed donor mock decoration ("Подзаголовок в две строки 20pt")
        # leaking through whenever the distributor produced a structural
        # donor with only the title slot filled and B5 dropped the overlay.
        # Two situations to disambiguate:
        #   Case A — distributor filled real body slots: drop overlay AND
        #       clear non-slot decoration only (keep the filled slot text).
        #   Case B — distributor filled only title/caption: keep the overlay
        #       (otherwise the slide has no content at all) AND clear ALL
        #       non-title text under the overlay.
        filled_body_slots_count = 0
        filled_slot_shape_indices: set[int] = set()
        if donor_def is not None:
            _slot_defs_local = donor_def.get("slots", {})
            for _slot_name, _slot_val in (plan_slide.get("slots") or {}).items():
                if _slot_name in ("title", "caption"):
                    continue
                if not str(_slot_val or "").strip():
                    continue
                if _slot_name not in _slot_defs_local:
                    continue
                filled_body_slots_count += 1
                _idx = _slot_defs_local[_slot_name].get("shape_idx")
                if isinstance(_idx, int):
                    filled_slot_shape_indices.add(_idx)

        case_a_drop_overlay = bool(
            info_shapes and donor_already_structural
            and filled_body_slots_count >= 2
        )
        if case_a_drop_overlay:
            print(
                f"infographic: SKIP donor={src_num} cat={donor_cat} "
                f"info_type={info_type} filled_body_slots={filled_body_slots_count} "
                "(skip-overlay rule B5/Case-A)", file=sys.stderr,
            )
            info_shapes = []
        elif info_shapes and donor_already_structural:
            # Case B: structural donor but distributor underfilled — keep
            # the overlay so the slide has actual content. Cleanup below
            # will wipe donor mock decoration before the overlay paints.
            print(
                f"infographic: KEEP donor={src_num} cat={donor_cat} "
                f"info_type={info_type} filled_body_slots={filled_body_slots_count} "
                "(Case-B: donor underfilled, overlay carries content)",
                file=sys.stderr,
            )

        needs_cleanup = bool(info_shapes) or case_a_drop_overlay
        if needs_cleanup and INFOGRAPHIC_RENDERER_AVAILABLE:
            try:
                # D1+D8 (2026-06-05): clear ALL non-title donor text before
                # injecting infographic shapes. Donors often have pre-labeled
                # boxes (process steps, comparison cells) whose labels aren't
                # in donor_def.slots — the old slot-only cleanup left them in
                # place, causing visual overlap with Agent 06's new boxes
                # (run1.slide7 verified). clear_donor_body_slots is now a
                # weaker layer behind the full-slide pass; we keep calling it
                # for the count.
                cleared = (
                    clear_donor_body_slots(actual, donor_def)
                    if donor_def and info_shapes else 0
                )
                if case_a_drop_overlay:
                    # Preserve filled-slot text so we don't wipe what the
                    # distributor put into sub*/body* slots.
                    cleared_all = clear_donor_non_title_text(
                        actual, preserve_shape_idx=filled_slot_shape_indices,
                    )
                else:
                    cleared_all = clear_donor_non_title_text(actual)
                added = (
                    render_infographic_shapes(actual, info_shapes)
                    if info_shapes else 0
                )
                if added or cleared or cleared_all:
                    print(
                        f"infographic: slide donor={src_num} type={info_block.get('type')} "
                        f"shapes_added={added}/{len(info_shapes)} "
                        f"donor_slots_cleared={cleared} non_title_cleared={cleared_all} "
                        f"case_a_drop_overlay={case_a_drop_overlay}",
                        file=sys.stderr,
                    )
            except Exception as e:  # noqa: BLE001 — never fail the build
                print(f"WARN: infographic render failed (donor {src_num}): {e}",
                      file=sys.stderr)
        elif info_shapes and not INFOGRAPHIC_RENDERER_AVAILABLE:
            print("WARN: infographic shapes present but infographic_renderer "
                  "module unavailable — skipping", file=sys.stderr)

        # PICTURES (вставляются ПОВЕРХ donor shapes)
        for pic in plan_slide.get("pictures", []):
            file_path = pic.get("file")
            if not file_path or not os.path.exists(file_path):
                print(f"WARN: image not found: {file_path}", file=sys.stderr)
                continue
            try:
                actual.shapes.add_picture(
                    file_path,
                    Emu(pic.get("left_px", 0) * EMU_PER_PX),
                    Emu(pic.get("top_px", 0) * EMU_PER_PX),
                    Emu(pic.get("width_px", 100) * EMU_PER_PX),
                    Emu(pic.get("height_px", 100) * EMU_PER_PX),
                )
                pictures_inserted += 1
            except Exception as e:
                print(f"WARN: insert_picture failed: {e}", file=sys.stderr)

        # TABLES (v8: fill_existing если donor имеет встроенную таблицу с брендовым стилем!)
        table_data = plan_slide.get("table_data")
        # D6 fix (2026-06-05): degenerate "tables" (one column, one row, or
        # missing cell content) render as a thin sliver — visual verifier
        # rejected slide as «table_native but no rows». Validate shape first;
        # when too thin, drop the table_data and let the body slot carry the
        # content as plain bullets.
        if table_data:
            is_degenerate = (
                not isinstance(table_data, list)
                or len(table_data) < 2
                or not any(isinstance(r, list) and len(r) >= 2 for r in table_data)
            )
            if is_degenerate:
                print(
                    f"WARN: table_data degenerate (rows={len(table_data) if isinstance(table_data, list) else 0}); "
                    f"skipping table render — content should already be in body slot",
                    file=sys.stderr,
                )
                table_data = None
        if table_data:
            try:
                # Найти существующую таблицу в donor (если есть)
                existing_table = None
                for sh in actual.shapes:
                    if sh.has_table:
                        existing_table = sh.table
                        break

                rows_needed = len(table_data)
                cols_needed = max(len(r) for r in table_data) if rows_needed else 1

                if existing_table:
                    # Donor уже имеет таблицу с брендовым стилем — заполняем её!
                    table_rows = len(existing_table.rows)
                    table_cols = len(existing_table.columns)
                    for r_idx, row_data in enumerate(table_data):
                        if r_idx >= table_rows:
                            break
                        for c_idx in range(table_cols):
                            cell = existing_table.cell(r_idx, c_idx)
                            if c_idx < len(row_data):
                                cell.text = str(row_data[c_idx])
                            else:
                                # Лишние колонки очищаем
                                cell.text = ""
                    # Очистить лишние строки если наш data короче
                    for r_idx in range(rows_needed, table_rows):
                        for c_idx in range(table_cols):
                            existing_table.cell(r_idx, c_idx).text = ""
                else:
                    # Donor не имеет таблицы — добавляем новую
                    left = Emu(35 * EMU_PER_PX)
                    top = Emu(120 * EMU_PER_PX)
                    width = Emu(1210 * EMU_PER_PX)
                    height = Emu(min(550, rows_needed * 50) * EMU_PER_PX)
                    tbl_shape = actual.shapes.add_table(rows_needed, cols_needed, left, top, width, height)
                    tbl = tbl_shape.table
                    for r_idx, row_data in enumerate(table_data):
                        for c_idx, cell_text in enumerate(row_data):
                            if c_idx >= cols_needed:
                                continue
                            tbl.cell(r_idx, c_idx).text = str(cell_text)
            except Exception as e:
                print(f"WARN: table fill failed: {e}", file=sys.stderr)

    # === FINAL: canonical enforcement над ВСЕМИ слайдами (для clone-based, где
    # native-фиксы не действуют). БЕЗОПАСНОЕ:
    #   - цвет: зелёный/белый текст → #222222 (кроме тёмного фона) [Problem #2]
    #   - вес: bold → SemiBold [Problem #3]
    #   - размер <12 → 12
    #   - заголовок контент-слайда → штатный TITLE-placeholder (35,38)/20pt
    #     SemiBold CAPS, СЕМАНТИЧЕСКИ (Вариант A) — не «угадывая по позиции»;
    #     титульные/divider и вертикальные/огромные заголовки не трогаются.
    # Bump до 16pt НЕ включаем — он даёт overflow на плотных/код-боксах. ===
    try:
        from enforce_canonical import enforce_canonical_slide, slide_is_dark
        enf_total = {}
        for slide in p.slides:
            st = enforce_canonical_slide(
                slide, dark=slide_is_dark(slide),
                min_pt=12, bump_from=None, bump_to=None, normalize_header=True)
            for k, v in st.items():
                enf_total[k] = enf_total.get(k, 0) + v
        if any(enf_total.values()):
            print(f"enforce_canonical: {enf_total}", file=sys.stderr)
    except Exception as e:
        print(f"WARN: enforce_canonical pass skipped: {e}", file=sys.stderr)

    # === FINAL: KPI emphasis (T2.2) ===
    # Detect digit-heavy runs in body text and bold+green them so 12pt
    # numbers buried in body actually catch the eye. Skips kpi_native
    # slides (render_kpi already styled them) and title-like runs.
    try:
        from kpi_emphasis import apply_kpi_emphasis
        emph_stats = apply_kpi_emphasis(p, plan_slides=plan["slides"])
        if emph_stats["total"]:
            print(f"kpi_emphasis: {emph_stats}", file=sys.stderr)
    except Exception as e:
        print(f"WARN: kpi_emphasis pass skipped: {e}", file=sys.stderr)

    p.save(output_path)
    print(f"Saved {output_path}: {len(p.slides)} slides, {pictures_inserted} pictures inserted",
          file=sys.stderr)

    # Финальная структурная валидация (ловит orphan-слайды / битые blip-картинки /
    # dangling rId — причины «PowerPoint обнаружил проблему с содержимым»).
    try:
        from validate_deck import validate_pptx
        _problems = validate_pptx(output_path)
        if _problems:
            print("⚠️  DECK VALIDATION: %d проблем(ы) — PowerPoint может ругаться:"
                  % len(_problems), file=sys.stderr)
            for _p in _problems[:30]:
                print("     -", _p, file=sys.stderr)
        else:
            print("✅ DECK VALIDATION: структурно чисто", file=sys.stderr)
    except Exception as _e:
        print(f"(validate_deck пропущен: {_e})", file=sys.stderr)


def main():
    if len(sys.argv) < 4:
        print("Usage: build_v7.py <plan.json> <template.pptx> <output.pptx> [donor-slot-map.yaml]",
              file=sys.stderr)
        sys.exit(1)
    plan_p = sys.argv[1]
    tpl_p = sys.argv[2]
    out_p = sys.argv[3]
    donor_p = sys.argv[4] if len(sys.argv) > 4 else "pptx-skill/brand/donor-slot-map.yaml"
    build(plan_p, tpl_p, out_p, donor_p)


if __name__ == "__main__":
    main()
