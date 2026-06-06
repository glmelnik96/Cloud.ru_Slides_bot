"""Deterministic classification of a parsed slide into a routing class.

Classes:
  none        — ordinary text slide; feature does not intervene.
  structured  — grouped text nodes forming a diagram → flow_diagram_native (C).
  raster      — slide carries a content-sized embedded picture → image (A).
  opaque      — visual slide with neither text structure nor raster → image (B).

Pure function — no I/O, no LLM. Thresholds are named constants.
"""

EMU_PER_PX = 9525

RASTER_MIN_AREA_PX = 200 * 200      # smaller is an icon/logo, not content
STRUCTURED_MIN_NODES = 3            # fewer is not a diagram
STRUCTURED_MAX_NODES = 8            # more does not fit presets → render whole (B)


def _has_normal_text(slide_data):
    title = (slide_data.get("title") or "").strip()
    body = [b for b in (slide_data.get("body") or []) if str(b).strip()]
    return bool(title) or len(body) >= 1


def _largest_image_area_px(slide_data):
    best = 0
    for im in slide_data.get("images") or []:
        w = im.get("width_emu") or 0
        h = im.get("height_emu") or 0
        area = (w / EMU_PER_PX) * (h / EMU_PER_PX)
        best = max(best, area)
    return best


def classify_visual_kind(slide_data):
    nodes = [n for n in (slide_data.get("group_nodes") or [])
             if str(n.get("text", "")).strip()]
    has_raster = _largest_image_area_px(slide_data) >= RASTER_MIN_AREA_PX

    if _has_normal_text(slide_data):
        return "none"
    if STRUCTURED_MIN_NODES <= len(nodes) <= STRUCTURED_MAX_NODES:
        return "structured"
    if has_raster:
        return "raster"
    return "opaque"
