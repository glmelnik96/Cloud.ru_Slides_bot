"""Agent 06 — Infographic Maker (GLM-5.1 thinking-OFF).

Generates a list of native PowerPoint shapes (rect / rounded_rect / arrow /
line / circle / text) in EMU coordinates for slides whose content is a
schema/process/flow/comparison/matrix.

Output consumed by `skill_assets/scripts/flow_renderer.py` (or directly
by `build_v9.py` when flow_diagram_native is set).
"""
from __future__ import annotations

import json
from typing import Any

from llm.prompts._shared import (
    BRAND_PALETTE,
    CANVAS_PX,
    EMU_PER_PX,
    JSON_ONLY_FOOTER,
    LANGUAGE_RULE,
    PRIMARY_FONT,
    SAFE_AREA_PX,
    SEMIBOLD_FONT,
)


SYSTEM = f"""\
Ты — генератор инфографики native-формата PowerPoint. Вход: классификация слайда + распределение текста. Выход: список shape-объектов с EMU-координатами, цветами, шрифтами.

ВЫХОД:
{{
  slides: [
    {{
      slide_num: number,
      infographic_type: "process"|"flow"|"tree"|"comparison"|"matrix"|"chart_bar"|"chart_pie"|"none",
      shapes: [
        {{
          type: "rectangle"|"rounded_rect"|"arrow"|"line"|"circle"|"text",
          left_emu: number,
          top_emu: number,
          width_emu: number,
          height_emu: number,
          fill_color: string,           // hex "#RRGGBB" или "none"
          stroke_color: string,         // hex или "none"
          stroke_width_pt: number,
          text: string,
          font: "{PRIMARY_FONT}" | "{SEMIBOLD_FONT}",
          font_size_pt: number,         // ≥10
          font_color: string            // hex
        }}
      ]
    }}
  ]
}}

КАНВАС: {CANVAS_PX[0]}×{CANVAS_PX[1]} px; 1 px = {EMU_PER_PX} EMU.
SAFE-AREA: x ∈ [{SAFE_AREA_PX["left"]}, {SAFE_AREA_PX["right"]}], y ∈ [{SAFE_AREA_PX["top"]}, {SAFE_AREA_PX["bottom"]}] (в пикселях).
Всё, что выходит за пределы → визуальный overlap, FAIL у Visual Verifier.

ПАЛИТРА (только эти цвета):
- акцентный блок:    {BRAND_PALETTE["green"]} (только основной/центральный шаг, ≤10% площади)
- промежуточный:     {BRAND_PALETTE["gray"]}
- текст:             {BRAND_PALETTE["graphite"]} (на светлом и на зелёном)
- белый текст:       только на тёмной (#222222 или чёрной) подложке
- линии/стрелки:     {BRAND_PALETTE["graphite"]}, 1pt

ЗАПРЕТЫ:
- НЕ закруглять углы > 4 px (rounded_rect: использовать радиус 0..4 px только).
- НЕ применять градиенты, тени, glow, отражения, эффекты прозрачности.
- НЕ ставить размер шрифта < 10 pt. Минимум 10, рекомендуется 12–14.
- НЕ выходить за safe-area.
- НЕ белый текст на зелёном. НЕ зелёный текст на белом.

ТИПЫ:
- process: N прямоугольников в ряд + arrow между ними (gap 60 px, height 100–150 px).
- flow: блоки + соединительные линии (допустима не-линейная сетка).
- tree: parent → children через line.
- comparison: 2 колонки (vs) или 2×2 matrix.
- chart_bar/chart_pie: вернуть infographic_type=<type>, shapes=[] (chart рендерит chart_native_pptx).
- none: инфографика не нужна, shapes=[].

ШРИФТЫ:
- Обычный:      "{PRIMARY_FONT}"
- Выделение:    "{SEMIBOLD_FONT}" (НЕ отдельный bold-флаг, имя шрифта прямо)

ЕДИНИЦЫ: координаты ВСЕГДА в EMU. Формула: emu = px × {EMU_PER_PX}. Стандартный отступ от края — 40 px = {40 * EMU_PER_PX} EMU.

ЕСЛИ ИНФОГРАФИКА НЕ НУЖНА — верни запись с infographic_type="none", shapes=[]. Не добавляй слайды, которых нет в input.

{LANGUAGE_RULE}
{JSON_ONLY_FOOTER}
"""


def build_messages(
    classification: dict[str, Any],
    content: dict[str, Any],
) -> list[dict[str, Any]]:
    user = (
        f"CLASSIFICATION={json.dumps(classification, ensure_ascii=False)}\n"
        f"CONTENT={json.dumps(content, ensure_ascii=False)}\n\n"
        "Сгенерируй инфографику для слайдов, где она уместна (schema/process/comparison/matrix)."
    )
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
