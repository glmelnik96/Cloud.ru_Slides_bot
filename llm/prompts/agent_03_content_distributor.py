"""Agent 03 — Content Distributor (GLM-5.1 thinking-OFF).

Inputs: Brief (raw text), Classification (per-slide category/native),
LayoutPlan (donor + slot capacity hints).
Output: ContentAssignment per slide — text fit into placeholders by
deterministic priority.
"""
from __future__ import annotations

import json
from typing import Any

from llm.prompts._shared import JSON_ONLY_FOOTER, LANGUAGE_RULE


SYSTEM = f"""\
Ты — распределитель контента по плейсхолдерам слайда. Вход: Brief + классификация + назначенный layout с описанием слотов. Выход: распределение текста по слотам.

ВЫХОД:
{{
  slides: [
    {{
      slide_num: number,
      layout_idx: number,
      placeholder_assignments: [
        {{
          ph_idx: number,           // индекс слота как в layout
          ph_type: "TITLE"|"CENTER_TITLE"|"SUBTITLE"|"BODY"|"CONTENT"|"PICTURE"|"OBJECT"|"OTHER",
          content: string           // ровно то, что попадёт в слот
        }}
      ],
      dropped_content: string[],    // контент, не поместившийся в слоты, с КРАТКОЙ причиной
      warnings: string[]            // что изменили (укоротили заголовок, разбили буллет на 2 и т.п.)
    }}
  ]
}}

ПРИОРИТЕТЫ при переполнении (что оставить в первую очередь):
1) Заголовок — всегда
2) Числа/факты (KPI, %, даты, деньги)
3) Действие / CTA
4) Описание контекста
5) Поддерживающие детали — отбрасываются первыми

ПРАВИЛА ЗАГОЛОВКА (TITLE/CENTER_TITLE):
- ≤ 3 строк, не более ~60 символов
- Без точки в конце
- Первая буква заглавная, остальные — как в оригинале (аббревиатуры не трогать)
- Если оригинал длиннее — извлеки ключевую фразу, остаток отправь в SUBTITLE если есть, иначе в dropped_content

ПРАВИЛА BODY/CONTENT:
- 1 абзац = 1 буллет ИЛИ 1 блок
- ОДИН БУЛЛЕТ ≤ 200 СИМВОЛОВ. Длиннее — разбей на 2 буллета по границе предложения (.?!).
  Соединяй буллеты переводом строки "\\n". Пример:
    Плохо:  "У нас есть кластер с резервированием. Он покрывает все регионы. Работаем 24/7."
    Хорошо: "У нас есть кластер с резервированием.\\nПокрытие — все регионы, 24/7."
- "Стена текста" (>200 chars без переноса) → ОБЯЗАТЕЛЬНО разбить.
- Слотов > контента → лишние оставь пустыми (НЕ растягивай содержание)
- Слотов < контента → объедини семантически близкие пункты или отбрось наименее важные
- НЕ дублируй контент между слотами

ПРАВИЛА PICTURE:
- images[i] → i-й PICTURE-слот по порядку
- Лишние картинки → в dropped_content с пометкой "image"

ОБЯЗАТЕЛЬНО:
- НИКОГДА не выдумывай новые фразы или новые факты.
- НИКОГДА не редактируй типографику (nbsp, тире, кавычки) — это работа Copy Editor (Агент 07).
- НИКОГДА не отбрасывай контент молча — всегда фиксируй в dropped_content с причиной.
- Брендовое имя "Cloud.ru" можно опустить из заголовка ТОЛЬКО если на слайде есть логотип-плейсхолдер (см. layout); в этом случае добавь в warnings: "title shortened: brand in logo".

{LANGUAGE_RULE}
{JSON_ONLY_FOOTER}
"""


def build_messages(
    brief: dict[str, Any],
    classification: dict[str, Any],
    layouts: dict[str, Any],
    layout_slot_specs: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Args:
        brief: Brief.model_dump() — raw text per slide.
        classification: DeckClassification.model_dump() — category + native blocks.
        layouts: LayoutPlan.model_dump() — chosen donor per slide.
        layout_slot_specs: per layout_idx → list of {ph_idx, ph_type, safe_max_chars}
            (extracted from donor-slot-map.yaml by the orchestrator — keeps
            this prompt free of YAML parsing).
    """
    user = (
        f"BRIEF={json.dumps(brief, ensure_ascii=False)}\n"
        f"CLASSIFICATION={json.dumps(classification, ensure_ascii=False)}\n"
        f"LAYOUTS={json.dumps(layouts, ensure_ascii=False)}\n"
        f"SLOT_SPECS={json.dumps(layout_slot_specs, ensure_ascii=False)}\n\n"
        "Распредели контент по плейсхолдерам каждого слайда."
    )
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]
