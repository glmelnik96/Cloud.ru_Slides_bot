"""Run 4 role-fit probes against all 3 models, print comparison table.

Probes (mirror real pipeline roles):
  A. Classifier      — tiny JSON {"type": "<one of 6>"} from slide text
  B. Brief parser    — small nested JSON from a markdown brief
  C. Designer        — large structured slide layout JSON
  D. Brand critic    — judgement under brand rules, structured verdict
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from _common import MODELS, make_client, timed_chat


# --------------------------- probe inputs ---------------------------

CLASSIFIER_INPUT = """
Slide raw content:
'Q1 2026 revenue grew to 12.4B RUB (+38% YoY). EBITDA margin 22%.
Net new logos: 142. Churn dropped to 3.1%. Customer NPS: 64.'
""".strip()

CLASSIFIER_SCHEMA = (
    'Return ONLY JSON: {"type": "<one of: kpi, chart, table, flow_diagram, image, text_only>"}'
)

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

DESIGNER_INPUT = """
Slide type: kpi
Content draft:
- Выручка Q1 2026: 12.4 млрд ₽ (+38% YoY)
- EBITDA margin: 22%
- Новые клиенты: 142
- Отток: 3.1%
Title hint: «Итоги Q1 2026»
""".strip()

DESIGNER_SCHEMA = """Return ONLY JSON exactly matching:
{
  "slide_title": str,
  "subtitle": str,
  "layout": "kpi_native",
  "kpis": [
    {"value": str, "label": str, "delta": str, "trend": "up"|"down"|"flat"},
    ... exactly 4 items ...
  ],
  "speaker_notes": str
}"""

CRITIC_INPUT = """
Brand rules (excerpt):
- Primary color: #2962FF; accent: #00C2FF; never use red except for negative deltas.
- Min font size: 14pt; titles 28-36pt.
- No more than 6 bullets per slide.
- Charts must include axis labels.

Slide under review (rendered description):
- Title 32pt #2962FF "Итоги Q1"
- 7 bullets, font 12pt, color #B00020 (dark red)
- Chart without Y-axis labels
""".strip()

CRITIC_SCHEMA = """Return ONLY JSON:
{
  "verdict": "PASS"|"WARN"|"FAIL",
  "score": int (0-100),
  "violations": [{"rule": str, "severity": "WARN"|"FAIL", "evidence": str}]
}"""


# --------------------------- evaluation helpers ---------------------------

def extract_json(text: str) -> Any | None:
    """Try to extract the first JSON object from arbitrary text."""
    if not text:
        return None
    # Strip ```json fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        # Greedy match the outermost {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        candidate = m.group(0) if m else None
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def get_content(resp) -> str:
    msg = resp.choices[0].message
    return (msg.content or "").strip()


@dataclass
class ProbeResult:
    model: str
    probe: str
    elapsed_s: float
    in_tokens: int
    out_tokens: int
    json_valid: bool
    schema_ok: bool
    notes: str


# --------------------------- per-probe schema checks ---------------------------

def check_classifier(obj: Any) -> tuple[bool, str]:
    valid_types = {"kpi", "chart", "table", "flow_diagram", "image", "text_only"}
    if not isinstance(obj, dict) or "type" not in obj:
        return False, "no .type"
    t = obj["type"]
    if t not in valid_types:
        return False, f"unknown type={t!r}"
    correct = t == "kpi"  # expected answer
    return correct, f"type={t}{' OK' if correct else ' WRONG (expected kpi)'}"


def check_brief(obj: Any) -> tuple[bool, str]:
    required = {"topic", "audience", "slide_count", "tone", "key_messages"}
    if not isinstance(obj, dict):
        return False, "not a dict"
    missing = required - obj.keys()
    if missing:
        return False, f"missing: {sorted(missing)}"
    ok = (
        isinstance(obj["slide_count"], int) and obj["slide_count"] == 8
        and isinstance(obj["key_messages"], list) and len(obj["key_messages"]) >= 3
    )
    return ok, f"slide_count={obj['slide_count']} msgs={len(obj['key_messages'])}"


def check_designer(obj: Any) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not a dict"
    required = {"slide_title", "subtitle", "layout", "kpis", "speaker_notes"}
    missing = required - obj.keys()
    if missing:
        return False, f"missing: {sorted(missing)}"
    kpis = obj.get("kpis")
    if not isinstance(kpis, list):
        return False, "kpis not list"
    if len(kpis) != 4:
        return False, f"kpis count={len(kpis)} (want 4)"
    for i, k in enumerate(kpis):
        if not isinstance(k, dict):
            return False, f"kpi[{i}] not dict"
        if not {"value", "label", "delta", "trend"} <= k.keys():
            return False, f"kpi[{i}] missing fields"
        if k["trend"] not in {"up", "down", "flat"}:
            return False, f"kpi[{i}].trend invalid"
    return True, f"layout={obj['layout']} kpis=4"


def check_critic(obj: Any) -> tuple[bool, str]:
    if not isinstance(obj, dict):
        return False, "not a dict"
    if obj.get("verdict") not in {"PASS", "WARN", "FAIL"}:
        return False, f"bad verdict={obj.get('verdict')!r}"
    if not isinstance(obj.get("score"), int):
        return False, "score not int"
    vio = obj.get("violations")
    if not isinstance(vio, list) or len(vio) < 2:
        return False, f"violations={len(vio) if isinstance(vio, list) else 'n/a'}"
    expected_fail = obj["verdict"] == "FAIL"  # red text + 7 bullets + 12pt is multiple FAILs
    note = f"verdict={obj['verdict']} score={obj['score']} viol={len(vio)}"
    return expected_fail, note


# Per-model max_tokens — reasoning models (GLM-5.1) need bigger budget to fit CoT + JSON.
MAX_TOK = {
    "zai-org/GLM-5.1":          {"A.classifier": 1500, "B.brief": 2500, "C.designer": 3500, "D.critic": 3500},
    "moonshotai/Kimi-K2.6":     {"A.classifier":  200, "B.brief":  400, "C.designer":  800, "D.critic":  700},
    "deepseek-ai/DeepSeek-V4-Pro": {"A.classifier":  200, "B.brief":  400, "C.designer":  800, "D.critic":  700},
}

PROBES: list[tuple[str, str, str, Callable[[Any], tuple[bool, str]]]] = [
    ("A.classifier", CLASSIFIER_INPUT, CLASSIFIER_SCHEMA, check_classifier),
    ("B.brief", BRIEF_INPUT, BRIEF_SCHEMA, check_brief),
    ("C.designer", DESIGNER_INPUT, DESIGNER_SCHEMA, check_designer),
    ("D.critic", CRITIC_INPUT, CRITIC_SCHEMA, check_critic),
]


# --------------------------- runner ---------------------------

def run() -> list[ProbeResult]:
    client = make_client()
    results: list[ProbeResult] = []
    for model in MODELS:
        for probe_name, user_input, schema, checker in PROBES:
            max_tok = MAX_TOK[model][probe_name]
            sys_msg = (
                "You are a structured-output assistant. "
                "Always reply with valid JSON only — no prose, no markdown fences."
            )
            user_msg = f"{user_input}\n\n{schema}"
            resp, elapsed, err = timed_chat(
                client,
                model=model,
                max_tokens=max_tok,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            if err:
                results.append(ProbeResult(model, probe_name, elapsed, 0, 0, False, False, f"ERR {err[:60]}"))
                continue
            content = get_content(resp)
            obj = extract_json(content)
            json_valid = obj is not None
            schema_ok, note = (False, "no json") if not json_valid else checker(obj)
            in_tok = getattr(resp.usage, "prompt_tokens", 0)
            out_tok = getattr(resp.usage, "completion_tokens", 0)
            results.append(ProbeResult(
                model, probe_name, elapsed, in_tok, out_tok, json_valid, schema_ok, note
            ))
            print(
                f"{model:<32} {probe_name:<13} {elapsed:>5.2f}s "
                f"in={in_tok:<4} out={out_tok:<4} "
                f"json={'Y' if json_valid else 'N'} ok={'Y' if schema_ok else 'N'}  {note}"
            )
    return results


def summarise(results: list[ProbeResult]) -> None:
    print("\n=== summary per model (lower latency, higher schema_ok = better) ===")
    print(f"{'model':<32} {'avg_lat':>8} {'sum_in':>7} {'sum_out':>8} {'json_ok':>8} {'schema_ok':>10}")
    for model in MODELS:
        mr = [r for r in results if r.model == model]
        if not mr:
            continue
        avg_lat = sum(r.elapsed_s for r in mr) / len(mr)
        sum_in = sum(r.in_tokens for r in mr)
        sum_out = sum(r.out_tokens for r in mr)
        json_ok = sum(1 for r in mr if r.json_valid)
        schema_ok = sum(1 for r in mr if r.schema_ok)
        print(
            f"{model:<32} {avg_lat:>7.2f}s {sum_in:>7} {sum_out:>8} "
            f"{json_ok}/{len(mr):<6} {schema_ok}/{len(mr):<8}"
        )


if __name__ == "__main__":
    print(f"{'model':<32} {'probe':<13} {'lat':>6} {'in':<7} {'out':<7} {'json':<6} {'ok':<5} note")
    print("-" * 110)
    res = run()
    summarise(res)
