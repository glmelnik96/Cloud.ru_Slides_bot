# Slides Bot

Telegram-бот для вёрстки .pptx по бренду Cloud.ru 2.0 на моделях Cloud.ru Foundation Models.

См. `PLAN.md` — источник истины по архитектуре и milestones.

## Локальный запуск (M1 foundation)

```bash
cp .env.example .env
# заполнить CLOUDRU_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_WHITELIST, REDIS_PASSWORD
cd docker
docker compose up --build
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
bot/         — python-telegram-bot (async)
worker/      — Celery prefork (sync), LangGraph runner
graph/       — LangGraph nodes (10 ролей)
llm/         — Cloud.ru FM client + role registry
renderers/   — адаптировано из Cloud.ru Slides Skill
storage/     — Redis client, S3, sessions
schemas/     — Pydantic для всех LLM-обменов
docker/      — compose + Dockerfiles + fonts
probes/      — research-пробы (переедут в tests/integration)
```

## Memory

Persistent agent memory: `C:\Users\Глеб\.claude\projects\C--Users------Documents-Slides-bot\memory\`
