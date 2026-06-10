"""A5: prompt tightening for CLASSIFIER / DISTRIBUTOR / INFOGRAPHIC_MAKER.

Each rule below traces to a documented live-run defect:
- card_grid fragmentation into degenerate cards (deck3 s4, 2026-06-08)
- section-heading leak into the last column (live run 2026-06-07)
- timeline per-card overflow (live run 2026-06-07)
- cover subtitle overflow (deck2, 2026-06-08)
- infographic JSON truncation → JSONDecodeError (cec58d4, 2026-06-07);
  max_tokens was cut 12000→8000 in B1, so the prompt must cap output size.

These tests pin the presence of the rules (marker substrings), not exact
wording — rewording is fine as long as the marker tokens survive.
"""
from __future__ import annotations

from llm.prompts.agent_02_slide_classifier import SYSTEM as CLASSIFIER
from llm.prompts.agent_03_content_distributor import SYSTEM as DISTRIBUTOR
from llm.prompts.agent_06_infographic_maker import SYSTEM as INFOGRAPHIC


class TestClassifierTightening:
    def test_card_grid_anti_fragmentation_rule(self):
        assert "АНТИ-ФРАГМЕНТАЦИЯ" in CLASSIFIER
        assert "ОДИН card_grid" in CLASSIFIER

    def test_card_grid_degenerate_cards_banned(self):
        # Cards of 1-2 words without a description must route to multicolumn.
        assert "1–2 слов" in CLASSIFIER


class TestDistributorTightening:
    def test_column_balance_rule(self):
        assert "РАВНОМЕРНО" in DISTRIBUTOR
        assert "col1_body" in DISTRIBUTOR

    def test_section_heading_leak_banned(self):
        assert "ЗАГОЛОВОК СЛЕДУЮЩЕГО РАЗДЕЛА" in DISTRIBUTOR
        assert "next-section heading" in DISTRIBUTOR

    def test_subtitle_cap(self):
        assert "SUBTITLE ≤ 120" in DISTRIBUTOR

    def test_timeline_per_card_cap(self):
        assert "TIMELINE" in DISTRIBUTOR
        assert "90 символов" in DISTRIBUTOR


class TestInfographicTightening:
    def test_shape_count_cap(self):
        assert "12 shapes" in INFOGRAPHIC

    def test_shape_text_cap(self):
        assert "100 символов" in INFOGRAPHIC

    def test_truncation_warning_present(self):
        # The model must understand WHY size matters: a truncated JSON loses
        # the whole infographics artefact (degrade-to-empty path).
        assert "усечённый JSON" in INFOGRAPHIC
