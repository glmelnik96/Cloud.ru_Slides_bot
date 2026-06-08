# Slides Bot — Implementation Plan

> ⚠️ **Исторический blueprint.** Milestones M1-M6 реализованы; проект в фазе доводки качества вёрстки. Актуальная структура и запуск — в `README.md`, актуальное состояние пайплайна — в коде (`graph/graph.py`, `graph/nodes/`). Этот документ сохранён как исходный замысел архитектуры и модельного стека.

**Original source of truth:** этот документ. `HANDOFF-pptx-bot.md` — исходный замысел, расхождения с реальностью Cloud.ru FM зафиксированы здесь.

**Last decision date:** 2026-06-04

---

## 1. Зафиксированная архитектура

| Компонент | Решение |
|---|---|
| Orchestration | LangGraph (sync, RedisSaver, `durability="sync"`) |
| Worker | Celery 5.5 prefork, sync tasks, `acks_late=True`, `prefetch_multiplier=1` |
| Bot | python-telegram-bot 22.x async, ConversationHandler для `brief_to_new` |
| Broker / state | Redis Stack 7.4 (один инстанс, разные `db` per concern) |
| Storage | S3 (Cloud.ru Object Storage) для templates, drafts, outputs, session bundles |
| LLM API | Cloud.ru Foundation Models (`https://foundation-models.api.cloud.ru/v1`) |
| Render | LibreOffice headless (.pptx → .pdf), pdftoppm (.pdf → .png) |

## 2. Модельный стек и роли

Все модели — через единую точку Cloud.ru FM, один API-ключ, OpenAI-compatible SDK.

| # | Роль | Модель | thinking | max_tok | extra_body |
|---|---|---|---|---|---|
| 1 | Brief Parser | `deepseek-ai/DeepSeek-V4-Pro` | — | 400 | `{}` |
| 2 | Slide Classifier ×N | `deepseek-ai/DeepSeek-V4-Pro` | — | 200 | `{}` |
| 3 | Outline Builder | `zai-org/GLM-5.1` | OFF | 1200 | `{"chat_template_kwargs":{"enable_thinking":False}}` |
| 4 | Copy Editor ×N | `deepseek-ai/DeepSeek-V4-Pro` | — | 400 | `{}` |
| 5 | Designer ×N | `zai-org/GLM-5.1` | OFF | 800 | `{"chat_template_kwargs":{"enable_thinking":False}}` |
| 6 | Distributor (donor map) | `zai-org/GLM-5.1` | OFF | 1200 | `{"chat_template_kwargs":{"enable_thinking":False}}` |
| 7 | Brand Guardian critic | `zai-org/GLM-5.1` | ON | 2500 | `{}` |
| 8 | Auto-fix protocol | `zai-org/GLM-5.1` | ON | 2500 | `{}` |
| 9 | Visual Verifier ×N (vision) | `moonshotai/Kimi-K2.6` | ON | 3000 | `{}` |
| 10 | Pixel-diff judge ×N (vision) | `moonshotai/Kimi-K2.6` | ON | 2000 | `{}` |

**Capability notes (проверено эмпирически 2026-06-04):**
- GLM-5.1 и DeepSeek-V4-Pro возвращают `400 not a multimodal model` на image_url.
- Kimi-K2.6 — единственная multimodal в стеке. thinking-toggle на vision-запросах **игнорируется** (всегда reasoning).
- DeepSeek-V4-Pro — non-reasoning, всегда самый быстрый.
- GLM-5.1 reasoning trace в `message.reasoning`; токены считаются в `completion_tokens`.
- Cloud.ru FM лимит: 20 RPS на API-ключ.

## 3. Структура репо

```
slides_bot/
├── bot/                          # python-telegram-bot
│   ├── app.py                    # PTB Application, dispatcher
│   ├── handlers/
│   │   ├── start.py              # /start + how-to + inline buttons
│   │   ├── verstai.py            # /verstai + reply на .pptx
│   │   ├── audit.py              # /audit
│   │   ├── brief.py              # /brief — Doc upload
│   │   ├── progress.py           # обновление status-message
│   │   ├── halt.py               # stop-the-line кнопки
│   │   └── resume.py             # /resume <session_id>
│   ├── middleware/
│   │   ├── whitelist.py          # TG user_id whitelist
│   │   └── single_session.py     # «одна задача — один user»
│   └── i18n/ru.py
├── worker/                       # Celery
│   ├── celery_app.py
│   ├── tasks/
│   │   ├── pipeline.py           # верхнеуровневая task: run LangGraph
│   │   ├── render.py             # soffice subprocess wrapper
│   │   └── cleanup.py            # tmp/session cleanup
│   └── progress.py               # pub/sub writer
├── graph/                        # LangGraph
│   ├── state.py                  # SessionState (Pydantic)
│   ├── nodes/
│   │   ├── brief_parser.py       # role 1
│   │   ├── classifier.py         # role 2
│   │   ├── outline_builder.py    # role 3
│   │   ├── copy_editor.py        # role 4
│   │   ├── designer.py           # role 5
│   │   ├── distributor.py        # role 6
│   │   ├── brand_guardian.py     # role 7
│   │   ├── autofix.py            # role 8
│   │   ├── visual_verifier.py    # role 9
│   │   ├── pixel_judge.py        # role 10
│   │   └── render_step.py        # syncs to renderer
│   ├── edges.py                  # conditional edges (3 retries, halt triggers)
│   └── graph.py                  # compile + RedisSaver
├── llm/
│   ├── client.py                 # OpenAI client with retry + RPS limiter
│   ├── roles.py                  # ROLE → model+toggle registry (см. таблицу §2)
│   ├── prompts/                  # промпты per role, адаптированные под модели
│   │   ├── _shared.py            # styleguide для GLM/DeepSeek/Kimi
│   │   ├── brief_parser.md
│   │   ├── classifier.md
│   │   ├── designer.md
│   │   └── ...
│   └── output_parsers.py         # Pydantic-валидация + 1 retry-with-feedback
├── renderers/                    # адаптировано из cloud-ru-slides skill v9.4
│   ├── build_v9.py
│   ├── flow_renderer.py
│   ├── table_renderer.py
│   ├── kpi_renderer.py
│   ├── chart_renderer.py
│   ├── image_renderer.py
│   └── brand_guardian.py         # XML-слой валидации (не LLM)
├── storage/
│   ├── s3.py                     # boto3 wrapper для Cloud.ru Object Storage
│   ├── redis_client.py
│   ├── session.py                # session bundle (.pptx, report.json, png-preview)
│   └── template_cache.py         # download + sha256-verify
├── schemas/                      # Pydantic models на каждый JSON-обмен с LLM
│   ├── brief.py
│   ├── slide.py
│   ├── brand_report.py
│   └── ...
├── tests/
│   ├── probes/                   # текущие probes/ переезжают сюда как regression
│   ├── unit/
│   ├── integration/              # реальные вызовы Cloud.ru, помечены slow
│   └── fixtures/
├── docker/
│   ├── Dockerfile.bot
│   ├── Dockerfile.worker         # ставит soffice + SB Sans + pdftoppm
│   ├── docker-compose.yml
│   └── fonts/SBSans*.otf
├── scripts/
│   ├── seed_whitelist.py
│   ├── upload_template.py
│   └── replay_session.py         # debug: re-run from checkpoint
├── .env.example
├── pyproject.toml
└── PLAN.md                       # этот файл
```

## 4. Workstreams (параллельные треки)

Идут параллельно после M1. Каждый — независимая ветка работы.

### WS-A: Bot UX / TG integration
- Onboarding, режимы, whitelist, прогресс, halt UI, resume, archive

### WS-B: Orchestration (Celery + LangGraph)
- State machine, checkpointing, retries, conditional edges, halt mechanics

### WS-C: LLM-layer
- Cloud.ru FM client с RPS-limiter, role registry, Pydantic parsers, retry-with-feedback

### WS-D: Renderers (port из cloud-ru-slides skill)
- `build_v9.py`, flow/table/kpi/chart/image, XML brand guardian, soffice render

### WS-E: Prompt re-engineering под GLM/DeepSeek/Kimi ⚠️ новое

Исходные промпты cloud-ru-slides скилла спроектированы под Claude — длинные системные инструкции, role-play («You are a senior brand designer with 15 years…»), «think step by step», nested XML examples. На GLM/DeepSeek/Kimi это:
- даёт более низкую JSON-fidelity
- провоцирует GLM/Kimi уходить в избыточный reasoning
- ухудшает recall критиков

**Подход:**
1. Каждый промпт переписать в **минималистичном structured-output стиле**:
   - короткий system: «You are a JSON generator. Output strictly schema X.»
   - схема в формате TypeScript-like signature (всегда работает лучше прозы)
   - 1-2 few-shot examples (без длинных reasoning chains)
   - explicit «no prose, no markdown fences, no commentary»
2. **Model-specific preambles**:
   - DeepSeek: ультра-сухо, минимум контекста, прямой constraint
   - GLM-OFF: schema + 1 example, без CoT
   - GLM-ON: «list issues exhaustively, then verdict» — критик выигрывает от структуры
   - Kimi-vision: «describe what you SEE, then JSON» — vision tasks без анти-reasoning, иначе модель «фантазирует»
3. **A/B harness** в `tests/probes/`: каждый промпт прогоняется на 3 fixture-кейсах per role, считается `(schema_ok, semantic_ok, latency, tokens)`. Изменение промпта = регрессионный прогон.
4. **Глоссарий terminology**: бренд-термины Cloud.ru, шаблонные слот-имена — выносится в `llm/prompts/_shared.py::CLOUD_RU_GLOSSARY` и инжектится во все промпты.

Этот трек начинается **в M3** одновременно с интеграцией первых нод и идёт до конца M5.

### WS-F: Storage + observability
- S3 buckets, Redis schema, structlog→Loki, Prometheus metrics, Sentry

### WS-G: Deploy / infra
- docker-compose, fonts, Redis Stack, soffice config (uniq `-env:UserInstallation` per worker pid)

---

## 5. Milestones

### M1 — Foundation (skeleton + Redis + whitelist)
**Goal:** бот отвечает на `/start`, проверяет whitelist, поднята вся инфра локально.

**Deliverables:**
- `docker-compose.yml`: redis-stack, bot, worker (одна реплика воркера)
- `bot/app.py` + `/start` handler с inline-кнопками режимов
- `middleware/whitelist.py` — список TG user_id из `.env`
- `llm/client.py` минимальный (smoke `/ping`)
- `tests/probes/00_smoke.py` переехал в `tests/integration/`

**Acceptance:**
- `docker compose up` → бот живой
- Whitelisted user видит меню, не-whitelisted получает «нет доступа»
- `pytest tests/integration/test_smoke.py` — все 3 модели отвечают

---

### M2 — LangGraph state machine + Celery wiring
**Goal:** пустой граф (заглушки-ноды) пропускает фейковый job от бота до результата, прогресс отображается в чате.

**Deliverables:**
- `worker/celery_app.py` + sync prefork конфигурация
- `graph/state.py` (SessionState — Pydantic)
- `graph/graph.py` с RedisSaver, 3 заглушка-ноды (parse → fake → finalize)
- `worker/progress.py` — Redis pub/sub `job:{id}:progress`
- `bot/handlers/progress.py` — async-listener pub/sub, дебаунс 3s, `editMessageText`
- Cancel: кнопка [Отменить] → `revoke(terminate=True)` + cleanup tmp
- Resume: `/resume <session_id>` поднимает state из чекпойнта

**Acceptance:**
- Юзер шлёт что угодно → бот ставит фейковый job, показывает прогресс «Этап 1/3… 2/3… 3/3», возвращает `result.txt`
- Cancel в середине пайплайна оставляет S3/tmp чистыми (нет orphaned файлов)
- Resume после рестарта воркера продолжает с того же этапа

---

### M3 — Renderer port + first real node (designer + soffice)
**Goal:** real .pptx на выходе из реального LLM-вызова + рендер в PNG.

**Deliverables:**
- `renderers/build_v9.py` + `kpi_renderer.py` адаптированы из скилла, прошли smoke-тесты с шаблоном
- `llm/roles.py` — реестр моделей с правильными extra_body
- `llm/output_parsers.py` — Pydantic + 1 retry-with-feedback
- `graph/nodes/designer.py` (роль 5) — GLM-5.1 thinking-off, генерит slide JSON
- `graph/nodes/render_step.py` — вызывает `build_v9.add_slide(...)` через `subprocess.run` для soffice (уникальный `-env:UserInstallation=/tmp/soffice_{pid}/`)
- `storage/template_cache.py` — pull `Cloud_ru_Template_2026.pptx` v5 из S3, sha-verify
- **WS-E старт**: переписан `designer.md` промпт под GLM, A/B-харнесс в `tests/probes/role_05_designer/`

**Acceptance:**
- Юзер: `/verstai` + reply на 3-страничный .pptx → бот возвращает новый `.pptx` с 3 KPI-слайдами
- A/B-харнесс показывает schema_ok ≥95% на 10 fixture-кейсах для designer

---

### M4 — Brand Guardian + 4-слойная валидация + auto-fix
**Goal:** работает полная цепочка валидации с repair-iterations.

**Deliverables:**
- `renderers/brand_guardian.py` (XML-слой) — port из скилла, threshold 70 как в исходнике
- `graph/nodes/brand_guardian.py` (роль 7) — LLM-критик GLM-5.1 thinking-ON
- `graph/nodes/visual_verifier.py` (роль 9) — Kimi-K2.6 vision
- `graph/nodes/pixel_judge.py` (роль 10) — Kimi-K2.6 vision diff
- `graph/nodes/autofix.py` (роль 8) — chain `content reduction → font shrink (≤25%, floor 14pt) → donor swap → slide split`, max 3 iterations
- `graph/edges.py` — conditional edges: validate → autofix → validate → … → halt-or-finalize
- Stop-the-line кейсы: merged cells, RACI, диагональные стрелки, отсутствие шаблона → HALT → бот шлёт кнопки `[Продолжить с компромиссом] [Отменить]` с таймаутом 1 час
- 5-мин напоминание перед таймаутом
- **WS-E**: промпты brand_guardian, autofix, visual_verifier, pixel_judge переписаны и зафиксированы регрессией

**Acceptance:**
- На fixture-деке с заведомо ломаными слайдами: brand_score ≥80 на финале, ≤3 autofix-iterations
- HALT-сценарий: бот корректно показывает кнопки, по таймауту делает auto-cancel, `/resume` поднимает с того же чекпойнта
- Visual verifier ловит ≥3/5 искусственно внесённых семантических ошибок (текст не соответствует chart, неверный лейбл KPI и т.п.)

---

### M5 — Три режима + S3 архив + классификатор/copy editor
**Goal:** все три заявленные команды работают end-to-end.

**Deliverables:**
- `graph/nodes/classifier.py` (роль 2) + `copy_editor.py` (роль 4) + `brief_parser.py` (роль 1) + `outline_builder.py` (роль 3) + `distributor.py` (роль 6)
- Полный workflow для `/verstai`: parse → classify → copy_edit → distribute → design ×N → render ×N → validate → autofix
- `/audit`: parse → render-snapshot → brand_guardian → visual_verifier → report.json + текстовое summary в чат (без правленого .pptx)
- `/brief`: bot принимает .doc/.docx → brief_parser → outline_builder → confirm-step с inline-кнопкой [✓ Рендерить] → дальше как verstai
- `storage/session.py` — bundle (`draft.pptx`, `result.pptx`, `report.json`, `preview/*.png`, `trace.jsonl`) в S3, TTL 7 дней
- Confirm-step перед стартом: «нашёл N слайдов, режим X, оценка ~Y мин» с [Запустить]/[Отмена]
- Архив: `/sessions` показывает последние 10, восстановление по `session_id`
- Файлы >50MB отклоняются с инструкцией разбить
- Single-session lock: вторая задача от того же user → «у вас уже идёт задача» + [Отменить текущую]
- **WS-E**: все оставшиеся промпты переписаны, regression-харнесс зелёный

**Acceptance:**
- Все три режима проходят smoke-сценарии на 3 разных деках
- Result-бандл лежит в S3 с правильным TTL, скачивается по `/sessions`
- Брошенная сессия (юзер заблокировал бота) — graceful cleanup без exception в логах

---

### M6 — Hardening + observability + deploy
**Goal:** готово к проду.

**Deliverables:**
- `storage/redis_client.py` — graceful reconnect, AOF persistence, monit
- structlog JSON → stdout (для прода → Loki) с маскировкой текстов слайдов (NDA)
- Prometheus метрики: `job_duration_seconds{stage,mode}`, `llm_tokens_total{role,model}`, `validation_failures_total{layer,severity}`, `halts_total`, `s3_bytes_total`
- Sentry интеграция (только exception, без bodies)
- Auto-resume after Redis/worker crash: «Произошёл сбой, продолжаю с слайда 7» — встроено в LangGraph через RedisSaver, но добавить тестовый сценарий
- Soffice cleanup: `try/finally` гарантирует `rm -rf /tmp/soffice_{pid}/`
- Rate limiter на 20 RPS к Cloud.ru FM (token bucket в Redis)
- Token logging (без лимита, но с per-session aggregation в трасе)
- Backup RDB → S3 daily cron
- Production docker-compose с restart policies, healthchecks

**Acceptance:**
- 24-часовой soak-test (50 случайных дек'ов): нет утечек памяти, нет orphaned soffice-процессов, нет потерянных сессий
- Kill-test: грохнуть воркер во время рендера → resume автоматический, юзер видит «продолжаю с слайда N»
- Все метрики собираются, дашборд в Grafana отрисовывается

---

## 6. Definition of Done (общий)

- Unit-тесты ≥80% покрытия для `graph/`, `llm/`, `storage/`
- Integration-тесты помечены `@pytest.mark.slow`, прогоняются на CI nightly
- Regression-харнесс промптов зелёный (`tests/probes/role_*`)
- Все промпты в `llm/prompts/*.md` с шапкой `# role / model / thinking / last_validated`
- Логи без секретов и без NDA-content
- `make dev-up` / `make dev-down` работают
- README + .env.example + Onboarding-doc «как добавить нового whitelisted юзера»

---

## 7. Открытые риски и допущения

1. **Cloud.ru FM SLA не публичен.** Закладываем 1 retry per LLM call с 2s backoff. Если в проде увидим >5% 5xx — поднимаем до 3 retries.
2. **Лимит 20 RPS на ключ.** При параллельной обработке 5 дек одновременно × 10 параллельных LLM-вызовов внутри = 50 RPS — упрёмся. **Mitigation:** sequential per-slide в рамках одной деки, max_concurrent_decks=3 в Celery (общий cap = 30 RPS, ниже лимита). Если узко — запросить квоту или второй ключ.
3. **Kimi vision thinking игнорирует toggle.** Закладываем стабильно ≥2500 max_tok для vision. Цена в токенах — не проблема (юзер подтвердил).
4. **Шаблон обновляется руками.** Раз в N месяцев — окей. Авто-валидация new template: скрипт `scripts/validate_template.py` прогоняет 5 эталонных деков на новой версии перед промотированием `active_template_version`.
5. **Адаптация промптов под модели — открытый scope.** Заложен трек WS-E на M3–M5, но реальный объём станет ясен после первых попыток. **Контрольная точка** в конце M3: если designer-промпт требует >10 итераций — пересматриваем сроки M4-M5.

---

## 8. Что НЕ делаем в MVP

- Голосовой ввод brief (Whisper) — отложено
- A/B сравнение со старым Claude-skill — отложено
- Мониторинг token-budget с лимитом — только логирование
- EN-локализация бота — отложено
- Кнопка фидбека под результатом — отложено
- Pre-signed S3 upload для файлов >50MB — отложено (пока инструкция разбить)
- Public-доступ — только whitelist
