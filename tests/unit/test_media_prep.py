"""media_prep produces image_path for raster (extract) and opaque (render)."""
from __future__ import annotations

import os
from pathlib import Path

from graph.nodes.pipeline import _media_prep_for_slide


def test_raster_uses_extracted_image(tmp_path, monkeypatch):
    # Stub extractor: return a fake extracted file for slide 9.
    extracted = tmp_path / "slide9_img1.png"
    extracted.write_bytes(b"\x89PNG\r\n")

    def fake_extract(pptx, outdir, manifest=None):
        return {"images": [{"slide_num": 9, "file": extracted.name,
                            "width_px": 1149, "height_px": 535}]}

    monkeypatch.setattr("graph.nodes.pipeline.extract_images_extract", fake_extract)
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=9, visual_kind="raster",
        extract_dir=tmp_path, render_pngs={},
    )
    assert path is not None and path.endswith("slide9_img1.png")


def test_opaque_uses_rendered_png(tmp_path):
    rendered = tmp_path / "slide-08.png"
    rendered.write_bytes(b"\x89PNG\r\n")
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=8, visual_kind="opaque",
        extract_dir=tmp_path, render_pngs={8: str(rendered)},
    )
    assert path == str(rendered)


def test_opaque_without_render_returns_none(tmp_path):
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=8, visual_kind="opaque",
        extract_dir=tmp_path, render_pngs={},
    )
    assert path is None
