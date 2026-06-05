"""Render a result .pptx in the slides-bot-worker container and build a PIL
contact sheet. Usage: python tmp/p11/render_sheet.py <result.pptx> <label>
Outputs tmp/p11/<label>_pngs/ and tmp/p11/<label>_sheet.png
"""
from __future__ import annotations
import subprocess, sys, os
from pathlib import Path
from PIL import Image

WORKER = "slides-bot-worker"


def sh(*args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr, file=sys.stderr)
        raise SystemExit(f"cmd failed: {' '.join(args)}")
    return r.stdout


def render(pptx: Path, label: str) -> Path:
    cdir = f"/tmp/{label}"
    sh("docker", "exec", WORKER, "rm", "-rf", cdir)
    sh("docker", "exec", WORKER, "mkdir", "-p", cdir)
    sh("docker", "cp", str(pptx), f"{WORKER}:{cdir}/in.pptx")
    sh("docker", "exec", WORKER, "python", "/app/skill_assets/scripts/render_slides.py",
       f"{cdir}/in.pptx", f"{cdir}/out/")
    outdir = Path("tmp/p11") / f"{label}_pngs"
    outdir.mkdir(parents=True, exist_ok=True)
    # clear old pngs
    for p in outdir.glob("*.png"):
        p.unlink()
    sh("docker", "cp", f"{WORKER}:{cdir}/out/.", str(outdir))
    return outdir


def sheet(pngdir: Path, label: str, cols: int = 3, thumb_w: int = 480) -> Path:
    imgs = sorted(p for p in pngdir.glob("slide*.png"))
    if not imgs:
        raise SystemExit(f"no slide PNGs in {pngdir}")
    thumbs = []
    for p in imgs:
        im = Image.open(p).convert("RGB")
        r = thumb_w / im.width
        thumbs.append(im.resize((thumb_w, int(im.height * r))))
    th = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    gap = 8
    W = cols * thumb_w + (cols + 1) * gap
    H = rows * th + (rows + 1) * gap
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    for i, t in enumerate(thumbs):
        r, c = divmod(i, cols)
        x = gap + c * (thumb_w + gap)
        y = gap + r * (th + gap)
        sheet.paste(t, (x, y))
    out = Path("tmp/p11") / f"{label}_sheet.png"
    sheet.save(out)
    return out


if __name__ == "__main__":
    pptx = Path(sys.argv[1])
    label = sys.argv[2]
    d = render(pptx, label)
    s = sheet(d, label)
    print(f"sheet: {s} ({len(list(d.glob('slide*.png')))} slides)")
