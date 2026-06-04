"""Inspect what Kimi-K2.6 returns on probe B (brief) — why it hits max_tokens."""
from __future__ import annotations

import json

from _common import make_client, timed_chat

BRIEF_INPUT = """
# Brief
Topic: Запуск нового тарифа Evolution Cloud для среднего бизнеса
Audience: ИТ-директора компаний 200-2000 сотрудников
Length: 8 slides
Tone: уверенный, без хайпа
Key messages:
- цена ниже конкурентов на 18%
- SLA 99.95%
- миграция за 14 дней
""".strip()

BRIEF_SCHEMA = """Return ONLY JSON with this shape:
{"topic": str, "audience": str, "slide_count": int, "tone": str, "key_messages": [str, ...]}"""


def main() -> None:
    client = make_client()
    resp, elapsed, err = timed_chat(
        client,
        model="moonshotai/Kimi-K2.6",
        max_tokens=2000,  # bigger budget
        temperature=0.0,
        messages=[
            {"role": "system", "content": "You are a structured-output assistant. Always reply with valid JSON only — no prose, no markdown fences."},
            {"role": "user", "content": f"{BRIEF_INPUT}\n\n{BRIEF_SCHEMA}"},
        ],
    )
    print(f"elapsed={elapsed:.2f}s err={err}")
    if not resp:
        return
    msg = resp.choices[0].message.model_dump()
    print("--- usage ---")
    print(json.dumps(resp.usage.model_dump(), indent=2))
    print("--- message keys ---")
    print(list(msg.keys()))
    print("--- content (first 1500 chars) ---")
    print(msg.get("content", "")[:1500])
    print("--- reasoning (first 800 chars) ---")
    print((msg.get("reasoning") or "")[:800])


if __name__ == "__main__":
    main()
