"""Output deck naming: `{session_id}_{source}.pptx`, tying a build to its run."""
from __future__ import annotations

from graph.nodes.pipeline import _output_filename


def test_includes_sanitised_source_stem():
    assert _output_filename("abc123", "Quarterly Report.pptx") == "abc123_Quarterly_Report.pptx"


def test_keeps_cyrillic_stem():
    assert _output_filename("abc123", "Презентация.pptx") == "abc123_Презентация.pptx"


def test_falls_back_when_no_source():
    assert _output_filename("abc123", None) == "abc123.pptx"
    assert _output_filename("abc123", "") == "abc123.pptx"


def test_strips_path_components_no_traversal():
    # A malicious/odd name must not inject path separators into the output name.
    out = _output_filename("abc123", "../../etc/passwd.pptx")
    assert out == "abc123_passwd.pptx"
    assert "/" not in out and "\\" not in out


def test_source_with_only_unsafe_chars_falls_back():
    # Stem collapses to empty after sanitising → bare session_id.
    assert _output_filename("abc123", "***.pptx") == "abc123.pptx"
