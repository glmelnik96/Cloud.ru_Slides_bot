"""Re-run role-fit with optimal thinking-toggle per model.
Goal: see if quality holds with thinking-OFF for fast/simple roles.
"""
from __future__ import annotations

from typing import Any

from _common import make_client, timed_chat

from importlib import import_module
m = import_module("02_role_fit")
PROBES = m.PROBES
extract_json = m.extract_json
get_content = m.get_content

# Per-model: optimal thinking-off extra_body
THINKING_OFF = {
    "zai-org/GLM-5.1": {"chat_template_kwargs": {"enable_thinking": False}},
    "moonshotai/Kimi-K2.6": {"thinking": {"type": "disabled"}},
    "deepseek-ai/DeepSeek-V4-Pro": {},  # no-op
}

# With thinking off we can use modest budgets
MAX_TOK = 700

MODELS = list(THINKING_OFF.keys())


def main() -> None:
    client = make_client()
    print(f"{'model':<32} {'probe':<13} {'lat':>6} {'in':>4} {'out':>4} json ok  note")
    print("-" * 110)
    summary: dict[str, dict[str, Any]] = {}
    for model in MODELS:
        agg = {"lat": 0.0, "out": 0, "in": 0, "json": 0, "ok": 0, "n": 0}
        for probe_name, user_input, schema, checker in PROBES:
            sys_msg = "You are a structured-output assistant. Always reply with valid JSON only — no prose, no markdown fences."
            user_msg = f"{user_input}\n\n{schema}"
            resp, elapsed, err = timed_chat(
                client,
                model=model,
                max_tokens=MAX_TOK,
                temperature=0.0,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                extra_body=THINKING_OFF[model],
            )
            if err:
                print(f"{model:<32} {probe_name:<13} ERR {err[:60]}")
                continue
            content = get_content(resp)
            obj = extract_json(content)
            json_valid = obj is not None
            schema_ok, note = (False, "no json") if not json_valid else checker(obj)
            in_tok = resp.usage.prompt_tokens
            out_tok = resp.usage.completion_tokens
            agg["lat"] += elapsed; agg["in"] += in_tok; agg["out"] += out_tok
            agg["json"] += int(json_valid); agg["ok"] += int(schema_ok); agg["n"] += 1
            print(f"{model:<32} {probe_name:<13} {elapsed:>5.2f}s {in_tok:>4} {out_tok:>4}  "
                  f"{'Y' if json_valid else 'N'}    {'Y' if schema_ok else 'N'}   {note}")
        summary[model] = agg

    print("\n=== summary (thinking OFF where supported) ===")
    print(f"{'model':<32} {'avg_lat':>8} {'sum_out':>8} {'json':>6} {'schema':>7}")
    for model, a in summary.items():
        print(f"{model:<32} {a['lat']/a['n']:>7.2f}s {a['out']:>8} {a['json']}/{a['n']:<4} {a['ok']}/{a['n']:<5}")


if __name__ == "__main__":
    main()
