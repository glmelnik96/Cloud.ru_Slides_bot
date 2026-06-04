"""Kimi-K2.6 vision deep-dive: thinking on/off, accuracy on synthetic slide."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from _common import make_client, timed_chat

OUT_PNG = Path(__file__).parent / "_slide_fixture.png"

PROMPT = (
    "You are a visual slide verifier. Looking at the attached slide PNG, return ONLY JSON "
    "(no prose, no fences):\n"
    '{"title": str, "bullet_count": int, "bullets": [str, ...], '
    '"kpi_value": str, "kpi_label": str, "dominant_header_color_hex": str}'
)

EXPECTED = {
    "title": "Q1 2026 Results",
    "bullet_count": 3,
    "kpi_value": "87%",
    "kpi_label": "Customer NPS",
    "header_color_hex_approx": "#2962FF",
}


def main() -> None:
    png = OUT_PNG.read_bytes()
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    client = make_client()
    variants = [
        ("thinking_ON (full budget)", {}, 3500),
        ("thinking_OFF", {"extra_body": {"thinking": {"type": "disabled"}}}, 1200),
    ]
    for label, kwargs, max_tok in variants:
        resp, elapsed, err = timed_chat(
            client,
            model="moonshotai/Kimi-K2.6",
            max_tokens=max_tok,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            **kwargs,
        )
        print(f"\n=== {label} (max_tok={max_tok}) ===")
        if err:
            print(f"  ERR  {err[:200]}")
            continue
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        reasoning_len = len(getattr(msg, "reasoning", "") or "")
        print(f"  elapsed={elapsed:.2f}s  in_tok={resp.usage.prompt_tokens} "
              f"out_tok={resp.usage.completion_tokens}  reasoning_len={reasoning_len}")
        print(f"  content: {content[:700]}")
        # Try to parse JSON
        try:
            # Strip possible fences
            txt = content
            if txt.startswith("```"):
                txt = txt.strip("`").lstrip("json").strip()
                # remove trailing fence
                if txt.endswith("```"):
                    txt = txt[:-3].strip()
            obj = json.loads(txt) if txt.startswith("{") else None
        except Exception as e:  # noqa: BLE001
            obj = None
            print(f"  JSON parse error: {e}")
        if obj:
            score = 0
            checks = []
            if obj.get("title", "").strip() == EXPECTED["title"]:
                score += 1; checks.append("title OK")
            else:
                checks.append(f"title={obj.get('title')!r}")
            if obj.get("bullet_count") == EXPECTED["bullet_count"]:
                score += 1; checks.append("bullet_count OK")
            else:
                checks.append(f"bullet_count={obj.get('bullet_count')}")
            if str(obj.get("kpi_value", "")).strip().rstrip(".") == "87%":
                score += 1; checks.append("kpi_value OK")
            else:
                checks.append(f"kpi_value={obj.get('kpi_value')!r}")
            if "NPS" in str(obj.get("kpi_label", "")):
                score += 1; checks.append("kpi_label OK (NPS)")
            else:
                checks.append(f"kpi_label={obj.get('kpi_label')!r}")
            hdr = str(obj.get("dominant_header_color_hex", "")).upper()
            if hdr.startswith("#29") or hdr.startswith("#28") or "2962" in hdr.upper():
                score += 1; checks.append(f"header_color OK ({hdr})")
            else:
                checks.append(f"header_color={hdr!r}")
            print(f"  ACCURACY: {score}/5  — {'; '.join(checks)}")


if __name__ == "__main__":
    main()
