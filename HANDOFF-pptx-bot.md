# HANDOFF — Cloud.ru PPTX Bot

**Project:** Telegram-бот для автоматической вёрстки `.pptx` презентаций
по фирменному стилю Cloud.ru.
**Owner:** Глеб Мельников · Cloud.ru in-house motion/video design team
**Status:** Ready for implementation
**Last updated:** 2026-06-03

---

## 0. TL;DR for the implementing agent

Прочитай этот файл целиком до начала работы. Затем выполни блок
**§9 Agent Bootstrap Commands** — это даст контекст исходного скилла и проверит
доступ к Cloud.ru API. После этого реализуй проект по плану из **§5**, начиная
с этапа 0.

Не пиши код раньше, чем выполнен §9. Если на каком-то шаге чего-то не хватает
(API-ключа, доступа к репо, шрифтов SB Sans) — останавливайся и зови
владельца. Никаких "временных моков" вместо реальных Cloud.ru вызовов.

---

## 1. Mission

Существующий Agent Skill `cloud-ru-slides` работает в Claude Desktop:
пользователь кидает в чат draft.pptx, Claude через десять агентов и Python-скрипты
производит свёрстанный по бренд-гайду результат.

Нужно перенести этот функционал в **Telegram-бот** с **production-бэкендом на
внутренних моделях Cloud.ru Foundation Models** — чтобы данные не уходили за
периметр и любой сотрудник Cloud.ru мог пользоваться через TG, без подписки
на Claude.

**Feature parity с v0.17 исходного скилла:**

- Три режима — `вёрстка из draft.pptx`, `новая презентация из brief.md`, `аудит существующей`
- Native slide types — KPI / image / chart / flow / table
- Canonical правила v2.x (kill_widows, anti-emoji, 100pt для трёхзначных чисел, и т.д.)
- Brand Guardian PASS ≥80/100 на baseline-кейсах
- Иерархия из 102 layouts шаблона `Cloud_ru_Template_2026.pptx`

---

## 2. Source materials

| Что | Где | Зачем |
|---|---|---|
| Исходный Agent Skill | https://github.com/mmd980508-create/cloud-ru-slides-skill | Базовая логика, промпты агентов, Python-скрипты, brand catalog |
| Cloud.ru FM — главная | https://cloud.ru/docs/foundation-models/ug/index | Общая документация |
| Cloud.ru FM — API ref | https://cloud.ru/docs/foundation-models/ug/topics/api-ref | OpenAI-совместимый API |
| Cloud.ru FM — модели | https://cloud.ru/docs/foundation-models/ug/topics/overview__available__models | Актуальный каталог |
| Cloud.ru FM — Quickstart | https://cloud.ru/docs/foundation-models/ug/topics/quickstart | Аутентификация, первый запрос |
| Cloud.ru FM — Function calling | https://cloud.ru/docs/foundation-models/ug/topics/api-ref__function-calling | Tools API |
| Cloud.ru FM — Structured output | https://cloud.ru/docs/foundation-models/ug/topics/api-ref__structured-output | JSON Schema responses |
| LangGraph docs | https://langchain-ai.github.io/langgraph/ | StateGraph, checkpointing, Send API |
| LangGraph + Redis checkpoint | https://github.com/redis-developer/langgraph-redis | `RedisSaver` для resume-from-middle |
| python-pptx docs | https://python-pptx.readthedocs.io/ | Парсинг и сборка .pptx |
| python-telegram-bot v20+ | https://docs.python-telegram-bot.org/ | TG API клиент |
| Celery docs | https://docs.celeryq.dev/ | Очередь долгих задач |
| LibreOffice headless | https://wiki.documentfoundation.org/Documentation/HowTo/Convert_files_from_the_command_line | Рендер .pptx → PNG |

---

## 3. Tech stack

**Required:**

- Python 3.11+
- `openai>=1.40` (используется только клиент, `base_url` подменяется на Cloud.ru)
- `python-telegram-bot>=20.7`
- `celery>=5.4` + `redis>=5.0`
- `fastapi>=0.110` (healthcheck, webhook-режим бота)
- `langgraph>=0.2` + `langgraph-checkpoint-redis>=0.1`
- `python-pptx>=0.6.23`
- `Pillow>=10.0`
- `pydantic>=2.6`
- `structlog>=24.1`
- LibreOffice 7.x с шрифтами SB Sans / SB Sans Text (для русского рендера)

**Optional:**

- `MinIO` или Cloud.ru Object Storage (S3-совместимое) — fallback для файлов >50MB
- `sentry-sdk` — ошибки
- `prometheus-client` — метрики

---

## 4. Architecture

```
[TG user] sends /verstai with .pptx attachment
    │
    ▼
[python-telegram-bot]  saves to /sessions/<uuid>/input.pptx
    │
    │  celery.send_task("verstai", {session_id, mode})
    ▼
[Redis broker]
    │
    ▼
[Celery worker]  invokes orchestrator.app.invoke(state, config)
                                            │
                                            ▼
                              ┌── LangGraph StateGraph ──┐
                              │  parse_pptx              │
                              │       │                  │
                              │       ▼                  │
                              │  brief_reader (GLM-5.1)  │
                              │       │                  │
                              │       ▼                  │
                              │  slide_classifier (GLM)  │
                              │       │                  │
                              │       ▼                  │
                              │  ┌── per_slide_loop ──┐  │
                              │  │  designer  (GLM)   │  │
                              │  │  distributor (GLM) │  │
                              │  │  validate_plan     │  │
                              │  │  build_single      │  │
                              │  │  render_to_png     │  │
                              │  │  verifier (Kimi)   │  │
                              │  │     │              │  │
                              │  │     ├─ PERFECT ────┼──► next_slide
                              │  │     └─ FAIL,retry<3┘  │  back to designer
                              │  └────────────────────┘  │
                              │       │                  │
                              │       ▼                  │
                              │  assemble_pptx           │
                              │       │                  │
                              │       ▼                  │
                              │  brand_guardian          │
                              └──────────┬───────────────┘
                                         │
                              [RedisSaver checkpoint after each slide]
                                         │
                                         ▼
                              /sessions/<uuid>/final.pptx + report.json
    │
    │  celery.AsyncResult.get()
    ▼
[python-telegram-bot]  sends final.pptx + report back to user
```

**LangGraph State (Pydantic):**

```python
class PptxState(BaseModel):
    session_id: str
    mode: Literal["verstai", "audit", "brief_to_new"]
    input_path: Path
    parsed: dict | None = None
    brief: dict | None = None
    classified: dict | None = None
    current_slide_idx: int = 0
    per_slide_results: list[SlideResult] = []
    retry_count: dict[int, int] = {}  # slide_idx -> retries
    final_pptx_path: Path | None = None
    final_report: dict | None = None
    errors: list[str] = []
    cost_tokens: dict[str, int] = {}  # model -> tokens
```

**Cloud.ru models по nodes:**

| Node | Model | Why |
|---|---|---|
| `brief_reader`, `slide_classifier`, `copy_editor` | `zai-org/GLM-5.1` или `deepseek-ai/DeepSeek-V4-Flash` | Text-only, дешёвые шаги |
| `designer`, `distributor`, `brand_guardian` | `zai-org/GLM-5.1` | Reasoning + structured output |
| `visual_verifier` | `moonshotai/Kimi-K2.6` | Vision: PNG-рендер → text verdict |

---

## 5. Implementation plan

**Phase 0 — Bootstrap (1 day).**
Структура репо, Docker Compose (api + worker + redis + minio), pinned deps в
`pyproject.toml`, `.env.example`, smoke-тест Cloud.ru API через `/v1/models`.
DoD: `docker compose up -d` поднимает стек, health-эндпоинт TG-бота отвечает 200.

**Phase 1 — Cloud.ru client (1-2 days).**
`src/cloudru_client.py`: метод `chat(messages, model, tools=None, response_format=None)`,
retry с экспоненциальным backoff на 429/5xx, логирование токенов, шорткаты
`glm()`, `kimi()`, `deepseek_flash()`.
DoD: unit-тесты на retry-логику, реальный пинг к каждой из трёх моделей.

**Phase 2 — Prompt adaptation (2-3 days).**
Промпты `agents/*.md` из исходного скилла адаптировать под GLM/Kimi:
- убрать Claude-специфичные XML-теги (`<thinking>`, `<verdict>`)
- заменить на JSON Schema через `response_format`
- упростить инструкции, нумеровать шаги (GLM лучше следует)
- прогнать regression-тесты исходного скилла, сравнить с baseline
DoD: каждый агент даёт валидный JSON по схеме на 95%+ запусков.

**Phase 3 — LangGraph orchestrator (3-4 days).**
`src/orchestrator.py` со StateGraph. Каждый шаг — отдельный node. Conditional
edges: `verifier → designer` при FAIL, иначе → next slide. `RedisSaver`
для чекпоинтов. Существующие скрипты (`parse_pptx.py`, `build_v9.py`,
`render_slides.py`, `brand_guardian.py`) вызываются из nodes как функции.
DoD: invoke на сэмпл-презентации проходит от start до END, чекпоинты в Redis
видны, resume после kill -9 работает.

**Phase 4 — TG bot UX (2-3 days).**
Команды `/verstai`, `/audit`, `/brief`. Inline-кнопки для режимов. Прогресс
через `editMessageText` ("Обработка слайда 3/15…"). Хранение user-state
в Redis. Antiflood (один user — одна задача в очереди).
DoD: end-to-end сценарий через TG-бот работает.

**Phase 5 — Render & vision verifier (2 days).**
Docker-образ воркера с `libreoffice-impress`, шрифтами SB Sans, и тестовым
рендером. Vision-вызов в Kimi K2.6: PNG в base64 → `image_url` в content,
парсинг verdict в JSON. Retry-логика встроена в LangGraph edges.
DoD: рендер корректный (без missing-glyph), verdict-парсер не падает на
"шумных" ответах.

**Phase 6 — Production (3 days).**
- Object Storage fallback для файлов >50MB → pre-signed URL
- Sentry + structlog в Loki
- Метрики: `verstai_duration_seconds`, `verstai_cost_rubles`, `verstai_brand_score`
- CI: black, ruff, mypy, pytest, security scan
- Документация для команды Cloud.ru
DoD: 5 пользователей прогоняют свои презентации, все три метрики собираются.

---

## 6. Known risks & caveats

| Risk | Mitigation |
|---|---|
| Промпты под Claude дают худший результат на GLM/Kimi (-15-25%) | Phase 2 — переписать формат, использовать structured output |
| Vision у Kimi слабее, чем у Claude → false PASS | Детерминистические pre-checks через `visual_validator_v2.py` PIL до LLM |
| TG лимит 50MB на исходящее сообщение | Phase 6 — fallback на S3 pre-signed URL |
| Долгие задачи (5-10 мин) vs TG 30-сек ack | Celery обязательно, прогресс через `editMessageText` |
| RPM-лимиты Cloud.ru на внутренние модели | MVP — sequential обработка слайдов; параллелизм после нагрузочного теста |
| Шрифты SB Sans на сервере | Phase 5 — положить в Docker-образ заранее |
| Шаблон `Cloud_ru_Template_2026.pptx` 29MB | Хранится локально на воркере, путь через env `CLOUD_RU_TEMPLATE` |
| Стоимость прогона | Метрики в Phase 6, оптимизация через DeepSeek-V4-Flash на дешёвых шагах |

---

## 7. Acceptance criteria

- [ ] TG-бот принимает `.pptx` и возвращает свёрстанный `.pptx` за <12 минут на 15-слайдовой презентации
- [ ] Brand Guardian PASS ≥80/100 на 5 baseline-кейсах исходного скилла
- [ ] LLM Visual Verifier ловит ≥80% поломок (overflow, missing content, наложение)
- [ ] LangGraph чекпоинт позволяет резюмировать после kill -9 worker'a без потерь
- [ ] JSON-логи каждой сессии с трекингом токенов, стоимости в рублях и длительности шагов
- [ ] `docker compose up -d` стартует весь стек на чистой Ubuntu 22.04 VM
- [ ] README с инструкцией деплоя и переменными окружения
- [ ] CI зелёный: black + ruff + mypy + pytest

---

## 8. Repository layout (target)

```
cloud-ru-pptx-bot/
├── HANDOFF.md                    ← этот файл
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── Dockerfile.api
├── Dockerfile.worker
├── src/
│   ├── __init__.py
│   ├── settings.py              ← pydantic-settings из .env
│   ├── cloudru_client.py        ← обёртка к Cloud.ru FM API
│   ├── orchestrator.py          ← LangGraph StateGraph
│   ├── state.py                 ← Pydantic-модель PptxState
│   ├── nodes/                   ← каждый node — отдельный модуль
│   │   ├── parse.py
│   │   ├── brief_reader.py
│   │   ├── classifier.py
│   │   ├── designer.py
│   │   ├── distributor.py
│   │   ├── builder.py
│   │   ├── renderer.py
│   │   ├── verifier.py
│   │   └── guardian.py
│   ├── bot/
│   │   ├── main.py              ← python-telegram-bot entrypoint
│   │   ├── handlers.py
│   │   └── progress.py          ← editMessageText updates
│   ├── celery_app.py
│   └── api.py                   ← FastAPI healthcheck
├── agents/                       ← .md промпты, адаптированные под GLM/Kimi
│   ├── 01-brief-reader.md
│   ├── ...
│   └── 10-llm-visual-verifier.md
├── scripts/                      ← портированные из исходного скилла
│   ├── parse_pptx.py
│   ├── build_v9.py
│   ├── kpi_renderer.py
│   ├── flow_renderer.py
│   ├── table_renderer.py
│   ├── render_slides.py
│   ├── brand_guardian.py
│   └── visual_validator_v2.py
├── brand/                        ← layouts dump, template analysis
│   ├── Cloud_ru_Template_2026.pptx
│   ├── layouts-dump.json
│   └── brand-rules.md
└── tests/
    ├── unit/
    ├── integration/
    └── regression/               ← baseline-кейсы из исходного скилла
```

---

## 9. Agent bootstrap commands

Запусти эти команды в указанном порядке. Если какая-то падает —
останавливайся, читай ошибку, не пытайся обходить.

```bash
# A. Studying source skill
mkdir -p /tmp/source-skills && cd /tmp/source-skills
git clone https://github.com/mmd980508-create/cloud-ru-slides-skill
cd cloud-ru-slides-skill
cat SKILL.md                                          # читать целиком
ls agents/                                            # инвентарь промптов
cat agents/01-brief-reader.md                         # пример
cat agents/10-llm-visual-verifier.md                  # критичный шаг
ls scripts/                                           # инвентарь скриптов

# B. Verifying Cloud.ru access
echo $CLOUD_RU_API_KEY                                # должен быть установлен
curl -s https://foundation-models.api.cloud.ru/v1/models \
     -H "Authorization: Bearer $CLOUD_RU_API_KEY" | jq

# C. Smoke-test GLM-5.1
curl -s https://foundation-models.api.cloud.ru/v1/chat/completions \
     -H "Authorization: Bearer $CLOUD_RU_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "model": "zai-org/GLM-5.1",
       "messages": [{"role": "user", "content": "ping"}]
     }' | jq

# D. Smoke-test Kimi K2.6 vision
# (заменить путь к тестовому PNG)
B64=$(base64 -w0 /tmp/test_slide.png)
curl -s https://foundation-models.api.cloud.ru/v1/chat/completions \
     -H "Authorization: Bearer $CLOUD_RU_API_KEY" \
     -H "Content-Type: application/json" \
     -d "{
       \"model\": \"moonshotai/Kimi-K2.6\",
       \"messages\": [{
         \"role\": \"user\",
         \"content\": [
           {\"type\": \"text\", \"text\": \"Describe in one sentence\"},
           {\"type\": \"image_url\", \"image_url\": {\"url\": \"data:image/png;base64,$B64\"}}
         ]
       }]
     }" | jq

# E. Reading LangGraph essentials before Phase 3
# (используй web_fetch или WebFetch tool агента)
# https://langchain-ai.github.io/langgraph/concepts/low_level/
# https://langchain-ai.github.io/langgraph/how-tos/persistence/
# https://github.com/redis-developer/langgraph-redis

# F. Verifying LibreOffice headless rendering
soffice --version                                     # должен быть 7.x
soffice --headless --convert-to png /tmp/source-skills/cloud-ru-slides-skill/tests/fixtures/sample.pptx \
        --outdir /tmp/render-test
ls /tmp/render-test/                                  # PNG-файлы должны появиться
```

---

## 10. Working agreements with the implementing agent

1. **Никаких моков вместо реального Cloud.ru API.** Если ключ не работает — остановиться и спросить владельца, а не дописывать заглушку.
2. **Сохранять артефакты каждой сессии под UUID.** `/sessions/<uuid>/{input,parsed.json,brief.json,classified.json,slides/,final.pptx,report.json,trace.jsonl}`.
3. **JSON-logs всегда.** Никакого `print()`. `structlog` с context binding per session_id.
4. **Не переписывать скрипты исходного скилла без причины.** Они работают и протестированы. Меняется только обёртка вокруг LLM-вызовов.
5. **Каждый Phase завершать smoke-тестом из соответствующего DoD.** Не переходить дальше, пока DoD не выполнен.
6. **Не вводить новые библиотеки без явного запроса.** Стек из §3 — это закрытый список. Расширение — только через approval владельца.
7. **Commits атомарные, по Phase.** Conventional commits: `feat(phase-3): orchestrator stategraph`, `fix(phase-2): glm prompt schema`.

---

## 11. Hand-off contact

Глеб Мельников — Telegram: уточнить у владельца. Часовой пояс UTC+3.
Ожидаемое время ответа: рабочие дни, ~2-4 часа.
