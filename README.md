# Slides Bot

Telegram-бот для вёрстки .pptx по бренду Cloud.ru 2.0 на моделях Cloud.ru Foundation Models.

`PLAN.md` и `HANDOFF-pptx-bot.md` — исходные blueprint'ы (M1-M6 реализованы); текущее состояние и архитектура отражены здесь и в коде.

## Локальный запуск

```bash
cp .env.example .env
# заполнить CLOUDRU_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_WHITELIST, REDIS_PASSWORD
cd docker
docker compose --env-file ../.env up --build
```

Стек: redis-stack, minio (S3), bot, worker. Пересборка после правок кода:

```bash
cd docker
docker compose --env-file ../.env build worker bot
docker compose --env-file ../.env up -d worker bot
```

Шрифты SB Sans положить в `docker/fonts/` до сборки worker-образа (исходник — материалы проекта `Cloud.ru Slides Skill`).

## Тесты

```bash
pip install -e ".[dev]"
pytest tests/unit              # быстрые, без сети
pytest -m slow                 # бьют по живому Cloud.ru FM (нужен .env)
```

## Структура

```
bot/           — python-telegram-bot (async)
worker/        — Celery prefork (sync), LangGraph runner, progress, skill_bridge
graph/         — LangGraph граф + ноды (agents.py — LLM-роли, pipeline.py — скрипт-ноды)
llm/           — Cloud.ru FM client, реестр ролей (llm/roles.py), промпты (llm/prompts/)
schemas/       — Pydantic для всех LLM-обменов и сессий
storage/       — Redis client, S3, sessions
skill_assets/  — бренд-шаблон + вендорные рендереры (scripts/build_v9.py, flow_renderer.py …)
scripts/       — утилиты (live_run.py — host-прогон пайплайна без Telegram/Celery)
docker/        — compose + Dockerfiles + fonts
tests/         — unit / integration / probes
```

### Пайплайн (16 нод, `graph/graph.py`)

```
parse → brief → classify → design → distribute → icons → infographic →
copyedit → assemble → build → brand → render_png → visual → process_verify
  → (autofix → assemble …) → finalize
```

LLM-роли (`llm/roles.py`): brief_parser, classifier, distributor, designer,
icon_picker, infographic_maker, copy_editor, visual_verifier,
brand_guardian_critic, autofix, outline_builder, pixel_judge.

## Memory

Persistent agent memory: `C:\Users\Глеб\.claude\projects\C--Users------Documents-Slides-bot\memory\`
