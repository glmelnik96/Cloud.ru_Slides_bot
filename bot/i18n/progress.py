"""Progress message templates and stage glossary (RU-only)."""
from __future__ import annotations

STAGE_RU: dict[str, str] = {
    "queued": "В очереди",
    "parsing": "Разбор входа",
    "classifying": "Классификация слайдов",
    "designing": "Сборка макетов",
    "rendering": "Рендер презентации",
    "validating": "Валидация бренда",
    "autofixing": "Авто-починка",
    "finalizing": "Финализация",
    "done": "Готово",
    "cancelled": "Отменено",
    "failed": "Ошибка",
    "halted": "Требуется решение",
}


def format_progress(stage: str, pct: int, detail: str = "") -> str:
    label = STAGE_RU.get(stage, stage)
    bar_len = 12
    filled = max(0, min(bar_len, round(bar_len * pct / 100)))
    bar = "█" * filled + "░" * (bar_len - filled)
    line = f"<b>{label}</b> {pct}%\n<code>{bar}</code>"
    if detail:
        line += f"\n<i>{detail}</i>"
    return line


def format_terminal(stage: str, error: str | None = None) -> str:
    if stage == "done":
        return "✅ <b>Готово</b>"
    if stage == "cancelled":
        return "🚫 <b>Отменено по запросу</b>"
    if stage == "halted":
        return "⏸️ <b>Требуется ваше решение</b>"
    if stage == "failed":
        msg = "❌ <b>Произошла ошибка</b>"
        if error:
            msg += f"\n<code>{error}</code>"
        return msg
    return f"<b>{STAGE_RU.get(stage, stage)}</b>"
