"""Synthetic upstream artefacts for WS-E probe tests.

Each probe test reads its specific upstream input (parsed_deck for 01,
brief for 02, classification for 03/04/05/06, content for 07, plan for 10)
from these factories so that an agent's failure doesn't cascade.

Sizes:
- small  — 3 slides (title + text + callout)
- medium — 8 slides (title, divider, 2 text, comparison, KPI, timeline, image)
- big    — 15 slides (medium + chart, table, flow schema, 2 split candidates)

The factories return plain dicts already shaped to match the Pydantic
schemas in `schemas/slides.py` — fed to ``model_validate`` they pass.
"""
from __future__ import annotations

from typing import Any, Literal

Size = Literal["small", "medium", "big"]
SIZES: tuple[Size, ...] = ("small", "medium", "big")


# ─── 1×1 transparent PNG (for vision-required probes) ───────────────────────

PIXEL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "AAIAAAoAAv/lxKUAAAAASUVORK5CYII="
)


# ─── ParsedDeck (input to Agent 01 Brief Reader) ─────────────────────────────

def make_parsed_deck(size: Size) -> dict[str, Any]:
    slides_small = [
        {"num": 1, "layout_name": "title", "title": "Cloud.ru Evolution Stack",
         "body": ["Платформа для AI-инфраструктуры"], "text_runs": [], "images": [],
         "shapes_count": 2, "tables_count": 0},
        {"num": 2, "layout_name": "text", "title": "Что внутри",
         "body": ["GPU-кластеры с Christofari Neo",
                  "MLOps пайплайны из коробки",
                  "Поддержка 24/7"],
         "text_runs": [], "images": [], "shapes_count": 4, "tables_count": 0},
        {"num": 3, "layout_name": "callout", "title": None,
         "body": ["Время до первого инференса — менее 15 минут"],
         "text_runs": [], "images": [], "shapes_count": 1, "tables_count": 0},
    ]
    slides_medium = slides_small + [
        {"num": 4, "layout_name": "divider", "title": "Метрики",
         "body": [], "text_runs": [], "images": [], "shapes_count": 1, "tables_count": 0},
        {"num": 5, "layout_name": "kpi", "title": "Рост за квартал",
         "body": ["+47% клиентов", "120 ТБ данных", "99.95% SLA"],
         "text_runs": [], "images": [], "shapes_count": 3, "tables_count": 0},
        {"num": 6, "layout_name": "timeline", "title": "Дорожная карта",
         "body": ["Q1: запуск beta", "Q2: enterprise tier",
                  "Q3: гибридное облако", "Q4: международные регионы"],
         "text_runs": [], "images": [], "shapes_count": 4, "tables_count": 0},
        {"num": 7, "layout_name": "comparison", "title": "До и после",
         "body": ["До: ручной деплой 4 часа", "После: автоматизация 8 минут"],
         "text_runs": [], "images": [], "shapes_count": 2, "tables_count": 0},
        {"num": 8, "layout_name": "image", "title": "Архитектура решения",
         "body": ["Схема Evolution Stack"], "text_runs": [],
         "images": [{"name": "arch.png", "left_emu": 0, "top_emu": 0,
                     "width_emu": 6000000, "height_emu": 4000000}],
         "shapes_count": 1, "tables_count": 0},
    ]
    slides_big = slides_medium + [
        {"num": 9, "layout_name": "chart", "title": "Динамика выручки",
         "body": ["2023: 1.2 млрд", "2024: 1.8 млрд", "2025: 2.7 млрд"],
         "text_runs": [], "images": [], "shapes_count": 1, "tables_count": 0},
        {"num": 10, "layout_name": "table", "title": "Тарифы",
         "body": ["Базовый — 50 000", "Бизнес — 150 000", "Enterprise — по запросу"],
         "text_runs": [], "images": [], "shapes_count": 0, "tables_count": 1},
        {"num": 11, "layout_name": "schema", "title": "Процесс onboarding",
         "body": ["Регистрация → KYC → Депозит → Запуск кластера → Мониторинг"],
         "text_runs": [], "images": [], "shapes_count": 5, "tables_count": 0},
        # Split candidate: 6 KPI numbers
        {"num": 12, "layout_name": "kpi", "title": "Технические показатели",
         "body": ["99.99% uptime", "<10мс latency", "10 ПБ хранилище",
                  "500+ инстансов", "200 ГБит/с сеть", "24/7 поддержка"],
         "text_runs": [], "images": [], "shapes_count": 6, "tables_count": 0},
        # Split candidate: 8 blocks
        {"num": 13, "layout_name": "multicolumn", "title": "Преимущества",
         "body": ["Безопасность", "Скорость", "Масштаб", "Цена",
                  "Поддержка", "Гибкость", "Совместимость", "Compliance"],
         "text_runs": [], "images": [], "shapes_count": 8, "tables_count": 0},
        {"num": 14, "layout_name": "team", "title": "Команда",
         "body": ["Анна Иванова — CEO", "Пётр Сидоров — CTO",
                  "Мария Петрова — Head of Product", "Олег Козлов — Head of Sales"],
         "text_runs": [], "images": [], "shapes_count": 4, "tables_count": 0},
        {"num": 15, "layout_name": "logo", "title": "cloud.ru", "body": [],
         "text_runs": [], "images": [], "shapes_count": 1, "tables_count": 0},
    ]
    slides = {"small": slides_small, "medium": slides_medium, "big": slides_big}[size]
    return {
        "file": f"probe_{size}.pptx",
        "slide_count": len(slides),
        "slide_size": {"width": 12192000, "height": 6858000},
        "slides": slides,
    }


# ─── Brief (input to Agent 02 Classifier) ────────────────────────────────────

def make_brief(size: Size) -> dict[str, Any]:
    base_slides_small = [
        {"num": 1, "raw_title": "Cloud.ru Evolution Stack",
         "raw_body": ["Платформа для AI-инфраструктуры"],
         "intent": "title", "key_phrase": "Платформа AI Evolution Stack",
         "elements_count": 2, "needs_visual": False},
        {"num": 2, "raw_title": "Что внутри",
         "raw_body": ["GPU-кластеры с Christofari Neo",
                       "MLOps пайплайны из коробки", "Поддержка 24/7"],
         "intent": "text", "key_phrase": "Состав платформы",
         "elements_count": 4, "needs_visual": False},
        {"num": 3, "raw_title": None,
         "raw_body": ["Время до первого инференса — менее 15 минут"],
         "intent": "callout", "key_phrase": "Старт за 15 минут",
         "elements_count": 1, "needs_visual": False},
    ]
    extra_medium = [
        {"num": 4, "raw_title": "Метрики", "raw_body": [],
         "intent": "divider", "key_phrase": "Раздел метрики",
         "elements_count": 1, "needs_visual": False},
        {"num": 5, "raw_title": "Рост за квартал",
         "raw_body": ["+47% клиентов", "120 ТБ данных", "99.95% SLA"],
         "intent": "data", "key_phrase": "Рост клиентов и SLA",
         "elements_count": 3, "needs_visual": False},
        {"num": 6, "raw_title": "Дорожная карта",
         "raw_body": ["Q1: запуск beta", "Q2: enterprise tier",
                       "Q3: гибридное облако", "Q4: международные регионы"],
         "intent": "timeline", "key_phrase": "План на год",
         "elements_count": 4, "needs_visual": False},
        {"num": 7, "raw_title": "До и после",
         "raw_body": ["До: ручной деплой 4 часа", "После: автоматизация 8 минут"],
         "intent": "comparison", "key_phrase": "Деплой быстрее в 30 раз",
         "elements_count": 2, "needs_visual": False},
        {"num": 8, "raw_title": "Архитектура решения",
         "raw_body": ["Схема Evolution Stack"],
         "intent": "image", "key_phrase": "Архитектура решения",
         "elements_count": 1, "needs_visual": True},
    ]
    extra_big = [
        {"num": 9, "raw_title": "Динамика выручки",
         "raw_body": ["2023: 1.2 млрд", "2024: 1.8 млрд", "2025: 2.7 млрд"],
         "intent": "chart", "key_phrase": "Рост выручки x2",
         "elements_count": 3, "needs_visual": True},
        {"num": 10, "raw_title": "Тарифы",
         "raw_body": ["Базовый — 50 000", "Бизнес — 150 000",
                       "Enterprise — по запросу"],
         "intent": "table", "key_phrase": "Три тарифа",
         "elements_count": 3, "needs_visual": False},
        {"num": 11, "raw_title": "Процесс onboarding",
         "raw_body": ["Регистрация → KYC → Депозит → Запуск кластера → Мониторинг"],
         "intent": "schema", "key_phrase": "Пять шагов запуска",
         "elements_count": 5, "needs_visual": True},
        {"num": 12, "raw_title": "Технические показатели",
         "raw_body": ["99.99% uptime", "<10мс latency", "10 ПБ хранилище",
                       "500+ инстансов", "200 ГБит/с сеть", "24/7 поддержка"],
         "intent": "data", "key_phrase": "Шесть KPI",
         "elements_count": 6, "needs_visual": False},
        {"num": 13, "raw_title": "Преимущества",
         "raw_body": ["Безопасность", "Скорость", "Масштаб", "Цена",
                       "Поддержка", "Гибкость", "Совместимость", "Compliance"],
         "intent": "comparison", "key_phrase": "Восемь преимуществ",
         "elements_count": 8, "needs_visual": False},
        {"num": 14, "raw_title": "Команда",
         "raw_body": ["Анна Иванова — CEO", "Пётр Сидоров — CTO",
                       "Мария Петрова — Head of Product", "Олег Козлов — Head of Sales"],
         "intent": "team", "key_phrase": "Команда из 4 человек",
         "elements_count": 4, "needs_visual": False},
        {"num": 15, "raw_title": "cloud.ru", "raw_body": [],
         "intent": "title", "key_phrase": "Закрывающий логотип",
         "elements_count": 1, "needs_visual": False},
    ]
    slides_map = {
        "small": base_slides_small,
        "medium": base_slides_small + extra_medium,
        "big": base_slides_small + extra_medium + extra_big,
    }
    slides = slides_map[size]
    return {
        "topic": "Cloud.ru Evolution Stack — AI-инфраструктура",
        "audience": "executives" if size != "small" else "unknown",
        "tone": "analytical" if size != "small" else "unknown",
        "slide_count": len(slides),
        "key_messages": [
            "Готовая платформа AI-инфраструктуры",
            "Быстрый старт — 15 минут до первого инференса",
            "Полная российская инфраструктура и поддержка",
        ],
        "has_numbers": size != "small",
        "has_quotes": False,
        "has_team": size == "big",
        "has_timeline": size != "small",
        "slides": slides,
    }


# ─── Classification (input to 03 Distributor, 04 Designer, 05 Icons, 06 Info) ─

def make_classification(size: Size) -> dict[str, Any]:
    base = [
        {"num": 1, "category": "title", "subcategory_hint": "white",
         "rationale": "первый слайд, заголовок продукта",
         "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 2, "category": "text", "subcategory_hint": "3bullets",
         "rationale": "заголовок + 3 буллета",
         "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 3, "category": "callout", "subcategory_hint": "white",
         "rationale": "одна короткая фраза",
         "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
    ]
    extra_medium = [
        {"num": 4, "category": "divider", "subcategory_hint": "dark",
         "rationale": "разделитель раздела", "slide_type": None, "dark": True,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 5, "category": "multicolumn", "subcategory_hint": "3kpi",
         "rationale": "3 KPI с описанием",
         "slide_type": "kpi_native", "dark": False,
         "kpi": {"title": "Рост за квартал",
                  "numbers": [
                      {"value": "47", "desc": "Рост клиентов", "pct": True, "accent": True},
                      {"value": "120", "desc": "ТБ данных", "pct": False, "accent": False},
                      {"value": "99.95", "desc": "SLA", "pct": True, "accent": False},
                  ]},
         "chart": None, "table": None, "flow": None, "image": None},
        {"num": 6, "category": "timeline", "subcategory_hint": "timeline_8",
         "rationale": "4 этапа дорожной карты",
         "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 7, "category": "multicolumn", "subcategory_hint": "2col",
         "rationale": "сравнение до/после",
         "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 8, "category": "image", "subcategory_hint": "illustration_half",
         "rationale": "иллюстрация архитектуры", "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
    ]
    extra_big = [
        {"num": 9, "category": "other", "subcategory_hint": "chart",
         "rationale": "график выручки", "slide_type": "chart_pptx_native", "dark": False,
         "kpi": None,
         "chart": {"type": "bar", "title": "Динамика выручки",
                   "caption": "млрд руб.", "x": ["2023", "2024", "2025"],
                   "series": [{"name": "Выручка", "data": [1.2, 1.8, 2.7]}],
                   "accent_idx": 2},
         "table": None, "flow": None, "image": None},
        {"num": 10, "category": "table", "subcategory_hint": "zebra",
         "rationale": "сравнительная таблица тарифов",
         "slide_type": "table_native", "dark": False,
         "kpi": None, "chart": None,
         "table": {"header": "Тарифы", "subtitle": "Прайс-лист",
                    "style": "zebra",
                    "headers": ["Тариф", "Цена", "Возможности"],
                    "data": [
                        ["Базовый", "50 000", "1 кластер, базовая поддержка"],
                        ["Бизнес", "150 000", "5 кластеров, приоритет"],
                        ["Enterprise", "по запросу", "SLA 99.99, dedicated"],
                    ],
                    "first_col_wider": True},
         "flow": None, "image": None},
        {"num": 11, "category": "other", "subcategory_hint": "flow",
         "rationale": "5-шаговая схема онбординга",
         "slide_type": "flow_diagram_native", "dark": False,
         "kpi": None, "chart": None, "table": None,
         "flow": {"header": "Процесс onboarding", "subtitle": "",
                   "grid": True, "cols": 5,
                   "blocks": [
                       {"id": "b1", "row": 1, "col": 1, "lines": ["Регистрация"]},
                       {"id": "b2", "row": 1, "col": 2, "lines": ["KYC"]},
                       {"id": "b3", "row": 1, "col": 3, "lines": ["Депозит"]},
                       {"id": "b4", "row": 1, "col": 4, "lines": ["Кластер"]},
                       {"id": "b5", "row": 1, "col": 5, "lines": ["Мониторинг"]},
                   ],
                   "arrows": [
                       {"from": "b1", "to": "b2"},
                       {"from": "b2", "to": "b3"},
                       {"from": "b3", "to": "b4"},
                       {"from": "b4", "to": "b5"},
                   ]},
         "image": None},
        # Split: Agent 02 would split 12 (6 KPI) into 12 + 12b, here pre-split.
        {"num": 12, "category": "multicolumn", "subcategory_hint": "3kpi",
         "rationale": "split часть 1/2", "slide_type": "kpi_native", "dark": False,
         "kpi": {"title": "Технические показатели (1/2)",
                  "numbers": [
                      {"value": "99.99", "desc": "Uptime", "pct": True, "accent": True},
                      {"value": "<10", "desc": "Latency, мс", "pct": False, "accent": False},
                      {"value": "10", "desc": "Хранилище, ПБ", "pct": False, "accent": False},
                  ]},
         "chart": None, "table": None, "flow": None, "image": None,
         "_source_slide": 12, "_split_part": "1/2"},
        {"num": 13, "category": "multicolumn", "subcategory_hint": "8blocks",
         "rationale": "8 преимуществ", "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 14, "category": "team", "subcategory_hint": "team_4",
         "rationale": "4 человека команды", "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
        {"num": 15, "category": "logo", "subcategory_hint": "closing",
         "rationale": "закрывающий логотип", "slide_type": None, "dark": False,
         "kpi": None, "chart": None, "table": None, "flow": None, "image": None},
    ]
    slides_map = {
        "small": base,
        "medium": base + extra_medium,
        "big": base + extra_medium + extra_big,
    }
    return {"slides": slides_map[size]}


# ─── LayoutPlan (input to Agent 03 Distributor) ──────────────────────────────

def make_layouts(size: Size) -> dict[str, Any]:
    """LayoutChoice serialises donor under alias ``layout_idx``."""
    # Pick plausible donors from the table in agent_04 prompt.
    by_num = {
        1: 1, 2: 25, 3: 24, 4: 9, 5: 44, 6: 39, 7: 69, 8: 46,
        9: 0, 10: 0, 11: 0, 12: 44, 13: 33, 14: 51, 15: 94,
    }
    n = {"small": 3, "medium": 8, "big": 15}[size]
    slides = []
    for num in range(1, n + 1):
        slides.append({
            "num": num,
            "layout_idx": by_num[num],
            "layout_name": "auto",
            "rationale": "fixture: deterministic donor pick",
            "slot_styles_override": {},
        })
    return {"slides": slides}


# ─── ContentAssignment deck (input to 05 Icons, 06 Infographic, 07 CopyEdit) ─

def make_content(size: Size) -> dict[str, Any]:
    """Plausible per-slide placeholder assignments. Hand-rolled to match
    the brief above; values are not the result of a real Distributor run.
    """
    base = [
        {"slide_num": 1, "layout_idx": 1,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "CENTER_TITLE",
              "content": "Cloud.ru Evolution Stack"},
             {"ph_idx": 1, "ph_type": "SUBTITLE",
              "content": "Платформа для AI-инфраструктуры"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 2, "layout_idx": 25,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Что внутри"},
             {"ph_idx": 1, "ph_type": "BODY",
              "content": "GPU-кластеры с Christofari Neo"},
             {"ph_idx": 2, "ph_type": "BODY",
              "content": "MLOps пайплайны из коробки"},
             {"ph_idx": 3, "ph_type": "BODY", "content": "Поддержка 24/7"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 3, "layout_idx": 24,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "BODY",
              "content": "Время до первого инференса -- менее 15 минут"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
    ]
    extra_medium = [
        {"slide_num": 4, "layout_idx": 9,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "CENTER_TITLE", "content": "Метрики"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 5, "layout_idx": 44,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Рост за квартал"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 6, "layout_idx": 39,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Дорожная карта"},
             {"ph_idx": 1, "ph_type": "BODY", "content": "Q1: запуск beta"},
             {"ph_idx": 2, "ph_type": "BODY", "content": "Q2: enterprise tier"},
             {"ph_idx": 3, "ph_type": "BODY", "content": "Q3: гибридное облако"},
             {"ph_idx": 4, "ph_type": "BODY", "content": "Q4: международные регионы"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 7, "layout_idx": 69,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "До и после"},
             {"ph_idx": 1, "ph_type": "BODY", "content": "До: ручной деплой 4 часа"},
             {"ph_idx": 2, "ph_type": "BODY", "content": "После: автоматизация 8 минут"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 8, "layout_idx": 46,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Архитектура решения"},
             {"ph_idx": 1, "ph_type": "PICTURE", "content": "arch.png"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
    ]
    extra_big = [
        {"slide_num": 9, "layout_idx": 0,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Динамика выручки"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 10, "layout_idx": 0,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Тарифы"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 11, "layout_idx": 0,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Процесс onboarding"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 12, "layout_idx": 44,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE",
              "content": "Технические показатели (1/2)"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 13, "layout_idx": 33,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Преимущества"},
             {"ph_idx": 1, "ph_type": "BODY", "content": "Безопасность"},
             {"ph_idx": 2, "ph_type": "BODY", "content": "Скорость"},
             {"ph_idx": 3, "ph_type": "BODY", "content": "Масштаб"},
             {"ph_idx": 4, "ph_type": "BODY", "content": "Цена"},
             {"ph_idx": 5, "ph_type": "BODY", "content": "Поддержка"},
             {"ph_idx": 6, "ph_type": "BODY", "content": "Гибкость"},
             {"ph_idx": 7, "ph_type": "BODY", "content": "Совместимость"},
             {"ph_idx": 8, "ph_type": "BODY", "content": "Compliance"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 14, "layout_idx": 51,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "TITLE", "content": "Команда"},
             {"ph_idx": 1, "ph_type": "BODY", "content": "Анна Иванова -- CEO"},
             {"ph_idx": 2, "ph_type": "BODY", "content": "Пётр Сидоров -- CTO"},
             {"ph_idx": 3, "ph_type": "BODY",
              "content": "Мария Петрова -- Head of Product"},
             {"ph_idx": 4, "ph_type": "BODY", "content": "Олег Козлов -- Head of Sales"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
        {"slide_num": 15, "layout_idx": 94,
         "placeholder_assignments": [
             {"ph_idx": 0, "ph_type": "CENTER_TITLE", "content": "cloud.ru"},
         ],
         "dropped_content": [], "warnings": [], "edits_count": 0},
    ]
    slides_map = {
        "small": base,
        "medium": base + extra_medium,
        "big": base + extra_medium + extra_big,
    }
    return {"slides": slides_map[size]}


# ─── Slot specs (input to 03 Distributor; mock until donor-slot-map wires) ───

def make_slot_specs(size: Size) -> dict[str, Any]:
    """Minimal mock: one entry per donor used in make_layouts.
    Real values from donor-slot-map.yaml land in chunk C.
    """
    return {
        "1":  [{"ph_idx": 0, "ph_type": "CENTER_TITLE", "safe_max_chars": 50},
                {"ph_idx": 1, "ph_type": "SUBTITLE", "safe_max_chars": 80}],
        "24": [{"ph_idx": 0, "ph_type": "BODY", "safe_max_chars": 120}],
        "25": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60},
                {"ph_idx": 1, "ph_type": "BODY", "safe_max_chars": 80},
                {"ph_idx": 2, "ph_type": "BODY", "safe_max_chars": 80},
                {"ph_idx": 3, "ph_type": "BODY", "safe_max_chars": 80}],
        "33": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60}] +
               [{"ph_idx": i, "ph_type": "BODY", "safe_max_chars": 40} for i in range(1, 9)],
        "39": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60}] +
               [{"ph_idx": i, "ph_type": "BODY", "safe_max_chars": 50} for i in range(1, 5)],
        "44": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60}],
        "46": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60},
                {"ph_idx": 1, "ph_type": "PICTURE", "safe_max_chars": 0}],
        "51": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60}] +
               [{"ph_idx": i, "ph_type": "BODY", "safe_max_chars": 60} for i in range(1, 5)],
        "69": [{"ph_idx": 0, "ph_type": "TITLE", "safe_max_chars": 60},
                {"ph_idx": 1, "ph_type": "BODY", "safe_max_chars": 80},
                {"ph_idx": 2, "ph_type": "BODY", "safe_max_chars": 80}],
        "9":  [{"ph_idx": 0, "ph_type": "CENTER_TITLE", "safe_max_chars": 40}],
        "94": [{"ph_idx": 0, "ph_type": "CENTER_TITLE", "safe_max_chars": 30}],
        "0":  [],  # native render — no donor slots
    }


# ─── Plan (input to Agent 10 Visual Verifier) ────────────────────────────────

def make_plan(size: Size) -> dict[str, Any]:
    """Minimal plan — donor route per slide. Real plan assembly lands in C."""
    n = {"small": 3, "medium": 8, "big": 15}[size]
    layouts = make_layouts(size)["slides"]
    slides = []
    for i, lay in enumerate(layouts[:n]):
        donor = lay["layout_idx"] or 1  # placeholder for native; Plan needs ≥1
        slides.append({
            "clone_from_slide": donor,
            "slots": {},
            "slot_styles_override": {},
        })
    return {"slides": slides}


# ─── Icon library (input to Agent 05) ───────────────────────────────────────

def make_icon_library() -> list[str]:
    """Static list — enough variety to let GLM avoid all-TODO fallbacks."""
    return [
        "icons/brand_arrow.svg", "icons/shield.svg", "icons/bolt.svg",
        "icons/scale.svg", "icons/people.svg", "icons/wallet.svg",
        "icons/cloud.svg", "icons/brain.svg", "icons/gear.svg",
        "icons/chart.svg", "icons/bulb.svg",
    ]
