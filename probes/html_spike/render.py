"""Check 0 fidelity spike — render hand-built brand templates to PNG via Playwright.

Isolated: reads only probes/html_spike/* and docker/fonts/*. Writes only out/.
No project code is imported or modified.
"""
from __future__ import annotations

import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONT_DIR = REPO / "docker" / "fonts"
TPL_DIR = HERE / "templates"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

W, H, SCALE = 1280, 720, 2


def _css_with_abs_fonts() -> str:
    css = (HERE / "brand.css").read_text(encoding="utf-8")
    font_base = FONT_DIR.as_uri()  # file:///.../docker/fonts

    def repl(m: re.Match) -> str:
        return f'url("{font_base}/{m.group(1)}")'

    return re.sub(r'url\("([^"]+\.otf)"\)', repl, css)


def _doc(css: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{css}</style></head><body>{body}</body></html>"
    )


def main() -> int:
    css = _css_with_abs_fonts()
    templates = sorted(TPL_DIR.glob("*.html"))
    if not templates:
        print("no templates found", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
        for tpl in templates:
            body = tpl.read_text(encoding="utf-8")
            full = _doc(css, body)
            full_path = OUT / f"{tpl.stem}.full.html"
            full_path.write_text(full, encoding="utf-8")
            page.goto(full_path.as_uri())
            page.wait_for_timeout(250)  # let fonts settle
            png = OUT / f"{tpl.stem}.png"
            page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": W, "height": H})
            print(f"rendered {tpl.name} -> {png.name}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
