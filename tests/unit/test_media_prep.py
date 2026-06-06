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


def test_raster_without_extractable_falls_back_to_render(tmp_path, monkeypatch):
    # Group-nested raster the non-recursive extractor can't see → empty manifest.
    rendered = tmp_path / "slide-11.png"
    rendered.write_bytes(b"\x89PNG\r\n")

    def fake_extract(pptx, outdir, manifest=None):
        return {"images": []}

    monkeypatch.setattr("graph.nodes.pipeline.extract_images_extract", fake_extract)
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=11, visual_kind="raster",
        extract_dir=tmp_path, render_pngs={11: str(rendered)},
    )
    assert path == str(rendered)


def test_raster_extract_raises_falls_back_to_render(tmp_path, monkeypatch):
    rendered = tmp_path / "slide-12.png"
    rendered.write_bytes(b"\x89PNG\r\n")

    def boom(pptx, outdir, manifest=None):
        raise RuntimeError("extractor blew up")

    monkeypatch.setattr("graph.nodes.pipeline.extract_images_extract", boom)
    path = _media_prep_for_slide(
        pptx_path=Path("dummy.pptx"), slide_num=12, visual_kind="raster",
        extract_dir=tmp_path, render_pngs={12: str(rendered)},
    )
    assert path == str(rendered)


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


def test_render_all_slides_indexes_by_num(tmp_path, monkeypatch):
    from graph.nodes import pipeline

    # Simulate render output: directory with slide-01.png .. slide-03.png
    out = tmp_path / "render"
    out.mkdir()
    for i in (1, 2, 3):
        (out / f"slide-{i:02d}.png").write_bytes(b"\x89PNG\r\n")

    def fake_run(*a, **k):
        class R: returncode = 0; stderr = ""
        return R()

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline.tempfile, "mkdtemp", lambda prefix="": str(out))

    mapping = pipeline._render_all_slides_png(tmp_path / "dummy.pptx")
    assert set(mapping.keys()) == {1, 2, 3}
    assert mapping[2].endswith("slide-02.png")
