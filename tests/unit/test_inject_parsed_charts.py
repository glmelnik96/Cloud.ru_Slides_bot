"""D (2026-06-07): native PPTX chart objects survive into the deck.

Taxonomy defect D: source charts/diagrams are lost ("0 pictures inserted").
``parse_pptx._extract_chart`` now reads chart series/categories, and
``_inject_parsed_charts`` deterministically restores a branded
``chart_pptx_native`` for any flat slide whose source held a native chart —
the LLM brief→classify chain drops the chart object, so this is the only path
that preserves the data.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), "..", "..", "skill_assets", "scripts"))

from graph.nodes.agents import _inject_parsed_charts  # noqa: E402
from parse_pptx import _chart_type_of, _num  # noqa: E402


def _cls(slides):
    return {"slides": slides}


def test_chart_type_mapping():
    assert _chart_type_of("COLUMN_CLUSTERED") == "bar"
    assert _chart_type_of("BAR_CLUSTERED") == "bar"
    assert _chart_type_of("COLUMN_STACKED") == "bar_stacked"
    assert _chart_type_of("BAR_STACKED_100") == "bar_stacked"
    assert _chart_type_of("LINE_MARKERS") == "line"
    assert _chart_type_of("XY_SCATTER") == "line"
    assert _chart_type_of("PIE") == "pie"
    assert _chart_type_of("DOUGHNUT") == "pie"
    assert _chart_type_of("AREA_STACKED") == "area_stacked"
    assert _chart_type_of("AREA_STACKED_100") == "area_100"
    assert _chart_type_of("SOMETHING_UNKNOWN") == "bar"


def test_num_coercion():
    assert _num(3) == 3.0
    assert _num("4.5") == 4.5
    assert _num(None) == 0.0
    assert _num("") == 0.0


def _parsed(chart):
    return {"slides": [{"num": 3, "title": "Выручка", "charts": [chart]}]}


def _chart(series, x=None, ctype="bar", title=""):
    return {"type": ctype, "title": title, "caption": "",
            "x": x if x is not None else ["2023", "2024", "2025"],
            "series": series, "accent_idx": 0}


def test_chart_injected_onto_flat_text_slide():
    parsed = _parsed(_chart([{"name": "Облако", "data": [1.0, 2.0, 3.0]}]))
    cls = _cls([{"num": 3, "slide_type": None, "category": "text",
                 "kpi": None, "chart": None, "table": None, "flow": None,
                 "image": None}])
    n = _inject_parsed_charts(cls, parsed)
    assert n == 1
    s = cls["slides"][0]
    assert s["slide_type"] == "chart_pptx_native"
    assert s["category"] == "other"
    assert s["chart"]["series"][0]["data"] == [1.0, 2.0, 3.0]
    assert s["chart"]["x"] == ["2023", "2024", "2025"]
    # title falls back to the parsed slide title when chart had none
    assert s["chart"]["title"] == "Выручка"


def test_chart_title_preserved_when_present():
    parsed = _parsed(_chart([{"name": "A", "data": [1.0]}], x=["q"],
                            title="Динамика ARR"))
    cls = _cls([{"num": 3, "slide_type": None, "category": "text"}])
    _inject_parsed_charts(cls, parsed)
    assert cls["slides"][0]["chart"]["title"] == "Динамика ARR"


def test_deliberate_native_not_overridden():
    parsed = _parsed(_chart([{"name": "A", "data": [1.0]}]))
    cls = _cls([{"num": 3, "slide_type": "kpi_native", "category": "text",
                 "kpi": {"numbers": [{"value": "1"}]}}])
    assert _inject_parsed_charts(cls, parsed) == 0
    assert cls["slides"][0]["slide_type"] == "kpi_native"


def test_split_part_not_touched():
    parsed = _parsed(_chart([{"name": "A", "data": [1.0]}]))
    cls = _cls([{"num": 3, "slide_type": None, "_split_part": "a"}])
    assert _inject_parsed_charts(cls, parsed) == 0


def test_chart_without_series_skipped():
    parsed = _parsed(_chart([]))  # no series
    cls = _cls([{"num": 3, "slide_type": None, "category": "text"}])
    assert _inject_parsed_charts(cls, parsed) == 0
    assert cls["slides"][0]["slide_type"] is None


def test_pie_with_no_categories_still_injects():
    parsed = _parsed(_chart([{"name": "share", "data": [60.0, 40.0]}],
                            x=[], ctype="pie"))
    cls = _cls([{"num": 3, "slide_type": None, "category": "text"}])
    assert _inject_parsed_charts(cls, parsed) == 1
    assert cls["slides"][0]["chart"]["type"] == "pie"


def test_source_slide_alias_matched():
    """A split-origin slide carries _source_slide instead of num."""
    parsed = _parsed(_chart([{"name": "A", "data": [1.0]}]))
    cls = _cls([{"num": 99, "_source_slide": 3, "slide_type": None,
                 "category": "text"}])
    assert _inject_parsed_charts(cls, parsed) == 1
