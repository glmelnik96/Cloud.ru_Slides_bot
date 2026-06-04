"""Agent 04 — Layout Designer (DeepSeek-V4-Pro).

Picks donor `layout_idx` (1..101) from Cloud.ru template for each slide
classified by Agent 02. Applies anti-monotony (no 3-in-a-row same donor).
DeepSeek terse style — lookup table embedded, no reasoning preamble.
"""
from __future__ import annotations

import json
from typing import Any

from llm.prompts._shared import JSON_ONLY_FOOTER, LANGUAGE_RULE


# Default donor table — extracted from `skill_assets/agents_reference/04-layout-designer.md`
# §"Category → Default idx mapping". Embedded in the prompt so DeepSeek
# doesn't need extra context fetch. Source of truth at runtime is
# `skill_assets/brand/donor-slot-map.yaml` — orchestrator validates.
DONOR_TABLE = """\
| category               | default | alternatives    |
| title                  | 1       | 6,8,54          |
| divider                | 9       | 55,10           |
| text                   | 25      | 28,34,67        |
| multicolumn:2col       | 69      | 26              |
| multicolumn:3col       | 32      | 73              |
| multicolumn:4blocks    | 29      | 70              |
| multicolumn:4subtitles | 30      | 71              |
| multicolumn:6blocks    | 31      | 72              |
| multicolumn:8blocks    | 33      | 74              |
| image:text+image       | 34      | 76,88           |
| image:half             | 45      | 48,88           |
| image:full             | 47      | —               |
| image:illustration_half| 46      | 89              |
| image:photo_full       | 90      | 92,93,95        |
| image:3-4_pictures     | 41      | 79,87           |
| image:screenshot       | 21      | 22,23           |
| team_3                 | 52      | 86              |
| team_4                 | 51      | 85              |
| team_5                 | 50      | 84              |
| team_10                | 49      | 83              |
| timeline:≤8            | 40      | 78              |
| timeline:9-10          | 39      | 77              |
| table                  | 36      | —               |
| callout:white          | 24      | —               |
| callout:dark           | 68      | —               |
| pattern_bg             | 14-20   | 59-66           |
| logo                   | 94      | 96              |
"""

# Tone groups for anti-monotony rotation (≤2 same idx in sequence).
TONE_GROUPS = """\
light_content:  [22, 29, 30, 32, 35, 43]
dark_content:   [23, 42, 58, 68]
green_accent:   [9, 13, 26, 96]
divider_set:    [10, 13, 14]
kpi_set:        [44, 45]
title_set:      [5, 6, 7, 8, 9]
"""


SYSTEM = f"""\
Ты — подборщик donor-слайдов из шаблона Cloud.ru. Вход: DeckClassification (категории и hint). Выход: LayoutPlan — donor (1..101) на каждый слайд.

ВЫХОД:
{{
  slides: [
    {{
      num: number,
      layout_idx: number,            // donor 1..101 (имя поля strictly "layout_idx")
      layout_name: string,           // короткое имя по таблице ("multicolumn 4blocks")
      rationale: string,             // 1 фраза
      slot_styles_override: object   // {{}} если не нужно; иначе локальные правки стилей
    }}
  ]
}}

ТАБЛИЦА КАТЕГОРИЯ → DONOR (используй default, alternatives — для anti-monotony):
{DONOR_TABLE}

ТОНОВЫЕ ГРУППЫ (для чередования):
{TONE_GROUPS}

ANTI-MONOTONY (детерминированно):
- НЕ ставь один и тот же layout_idx 3 раза подряд.
- Если 2 предыдущих слайда уже того же idx → возьми alternative из таблицы или соседний idx из tone-группы.
- Чередуй light/dark: ≤40% тёмных слайдов в колоде.

КАНОНИЧЕСКИЕ ПРАВИЛА (НЕ нарушай):
- НИКОГДА не выбирай layout_idx=101 (deprecated "clear").
- Команда (team): donor подбирается по числу людей (3→52, 4→51, 5→50, 10→49); НЕ растягивай контент.
- KPI native (slide_type=kpi_native) → layout_idx по умолчанию 44 (или 45 для dark).
- chart_pptx_native / table_native / flow_diagram_native / image_native → НЕ нужен donor: ставь layout_idx=0 и в rationale "native render — donor not applicable". Оркестратор обработает.

SLOT_STYLES_OVERRIDE (заполняй ТОЛЬКО при необходимости):
- {{"size_pt": <int>}} — если канонический размер не подходит (overflow); минимум 12pt, никогда меньше.
- {{"remove_shapes": [<ph_idx>]}} — если плейсхолдер не нужен на этом слайде.
- Цвета НЕ менять — color = #222222 (графит) на светлом, белый на тёмном; зелёного текста не бывает.

OVERFLOW STRATEGY (выбирай первый подходящий):
1) Donor с большим safe_max_chars в той же группе.
2) Split — но split уже сделан Агентом 02; если всё ещё переполнено — note в rationale.
3) Понизь размер в slot_styles_override (≥12pt).

{LANGUAGE_RULE}
{JSON_ONLY_FOOTER}
"""


def build_messages(classification: dict[str, Any]) -> list[dict[str, Any]]:
    user = (
        f"CLASSIFICATION={json.dumps(classification, ensure_ascii=False)}\n\n"
        "Подбери donor для каждого слайда. Применяй anti-monotony."
    )
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
