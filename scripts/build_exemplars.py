"""Render the chosen reference template pages to per-archetype exemplar PNGs.

These feed the composer as a vision few-shot ("target this look") and are the
ground truth for visual validation of each skeleton.

Usage: python -m scripts.build_exemplars
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

TEMPLATE = Path("skill_assets/Cloud.ru_Template_2026.pptx")
OUT = Path("skill_assets/brand/references/exemplars")

# archetype -> 1-based template page number (verified visually 2026-06-08).
ARCHETYPE_PAGE = {
    "cover_green": 1,       # green fill, graphite display title, dot grid + portal
    "cover_dark": 6,        # graphite, green-outline title box, descriptor plate
    "section_divider": 6,
    "points_3": 36,         # green full-width divider above bold head + text
    "points_4": 36,
    "points_6": 36,
    "points_8": 36,
    "bullet_list": 36,
    "table_zebra": 52,      # uniform green header (white text), periwinkle accent col
    "chart_columns": 45,    # green lead + periwinkle/mint/yellow/lilac ramp
    "roadmap_timeline": 61,  # green axis + square ticks + colored chips
}


def main() -> int:
    from scripts.render_png import pptx_to_pdf
    if not TEMPLATE.is_file():
        print(f"ERROR: template not found: {TEMPLATE}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    pdf = pptx_to_pdf(TEMPLATE, OUT)
    doc = fitz.open(pdf)
    mat = fitz.Matrix(1.5, 1.5)
    for arch, page_no in ARCHETYPE_PAGE.items():
        page = doc[page_no - 1]
        (OUT / f"{arch}.png").write_bytes(page.get_pixmap(matrix=mat).tobytes("png"))
        print(f"{arch} <- p{page_no}", flush=True)
    doc.close()
    # The intermediate PDF is large; drop it.
    pdf.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
