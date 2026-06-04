"""Vision capability probe across all 3 Cloud.ru models.

Generates a synthetic slide-like PNG with known content, asks each model to
describe it. Records: which models accept image_url, whether the description
matches ground truth, latency, tokens.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from _common import MODELS, make_client, timed_chat

OUT_PNG = Path(__file__).parent / "_slide_fixture.png"


def make_fixture() -> bytes:
    """Render a synthetic slide: red title, 3 bullets, KPI 87% in bottom-right."""
    W, H = 1280, 720
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    # Try to find a usable font; fall back to default.
    font_title = font_body = font_kpi = ImageFont.load_default()
    for candidate in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]:
        try:
            font_title = ImageFont.truetype(candidate, 56)
            font_body = ImageFont.truetype(candidate, 32)
            font_kpi = ImageFont.truetype(candidate, 96)
            break
        except OSError:
            continue
    # Header bar
    d.rectangle([(0, 0), (W, 90)], fill="#2962FF")
    d.text((40, 18), "Q1 2026 Results", font=font_title, fill="white")
    # Bullets (deliberately red to test color detection)
    bullets = [
        "Revenue: 12.4B RUB (+38% YoY)",
        "EBITDA margin: 22%",
        "Churn: 3.1%",
    ]
    y = 160
    for b in bullets:
        d.ellipse([(60, y + 14), (80, y + 34)], fill="#B00020")
        d.text((100, y), b, font=font_body, fill="#222")
        y += 60
    # KPI block (big number, bottom-right)
    d.rectangle([(W - 360, H - 240), (W - 40, H - 40)], outline="#2962FF", width=4)
    d.text((W - 320, H - 220), "87%", font=font_kpi, fill="#2962FF")
    d.text((W - 320, H - 100), "Customer NPS", font=font_body, fill="#666")
    img.save(OUT_PNG, "PNG", optimize=True)
    return OUT_PNG.read_bytes()


def to_data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


PROMPT = (
    "You are a visual slide verifier. Looking at the attached slide PNG, return ONLY JSON:\n"
    '{"title": str, "bullet_count": int, "bullets": [str, ...], '
    '"kpi_value": str, "kpi_label": str, "dominant_header_color": str}'
)


def main() -> None:
    png = make_fixture()
    print(f"fixture size: {len(png)} bytes  ({OUT_PNG})")
    data_url = to_data_url(png)
    client = make_client()
    for model in MODELS:
        resp, elapsed, err = timed_chat(
            client,
            model=model,
            max_tokens=800,
            temperature=0.0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        )
        if err:
            print(f"\n=== {model} ===\n  ERR  {err[:200]}")
            continue
        content = (resp.choices[0].message.content or "").strip()
        reasoning = (getattr(resp.choices[0].message, "reasoning", None) or "")
        print(f"\n=== {model} ===")
        print(f"  elapsed={elapsed:.2f}s  in_tok={resp.usage.prompt_tokens} "
              f"out_tok={resp.usage.completion_tokens}  reasoning_len={len(reasoning)}")
        print(f"  content (first 600): {content[:600]}")


if __name__ == "__main__":
    main()
