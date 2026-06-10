"""A4: donor capacity scoring — upgrade undersized donors at design time.

The Layout Designer picks donors by content TYPE; it has only a rough
max_chars hint and routinely sends text-heavy slides to small donors
(content_text holds 140 comfortable chars — a 600-char slide there ends
up clipped/cramped). ``donor_map.body_capacity`` sums the comfortable
budget across body slots; ``upgrade_donor_for_volume`` swaps the pick for
the smallest content-family donor that fits when the volume exceeds
``CAPACITY_OVERLOAD_RATIO`` × capacity. ``design_node`` applies it after
the validity repair pass.

Capacities asserted here come from donor-slot-map.yaml (content family:
21/22→140, 28→350, 34→525, 29→560, 33/35→720).
"""
from __future__ import annotations

from graph import donor_map


class TestBodyCapacity:
    def test_text_donor(self):
        assert donor_map.body_capacity(21) == 140

    def test_multicolumn_donor_sums_all_body_slots(self):
        # donor 28: col1_body + col2_body, 250 hard / 175 safe each.
        assert donor_map.body_capacity(28) == 350

    def test_title_donor_has_no_body(self):
        assert donor_map.body_capacity(4) == 0

    def test_native_and_unknown(self):
        assert donor_map.body_capacity(0) == 0
        assert donor_map.body_capacity(9999) == 0


class TestUpgradeDonorForVolume:
    def test_fitting_content_keeps_donor(self):
        assert donor_map.upgrade_donor_for_volume(21, "text", 100) is None

    def test_moderate_overflow_within_ratio_kept(self):
        # 450 ≤ 1.5 × 350 — the distributor can squeeze that much.
        assert donor_map.upgrade_donor_for_volume(28, "multicolumn", 450) is None

    def test_overloaded_text_slide_upgrades_to_fitting_donor(self):
        new = donor_map.upgrade_donor_for_volume(21, "text", 600)
        assert new is not None and new != 21
        assert donor_map.body_capacity(new) >= 600

    def test_huge_volume_falls_back_to_max_capacity(self):
        new = donor_map.upgrade_donor_for_volume(21, "text", 5000)
        assert new is not None
        assert donor_map.body_capacity(new) == 720  # largest content donor

    def test_dark_slide_untouched(self):
        # Content-family upgrades are light donors; a dark slide must keep tone.
        assert donor_map.upgrade_donor_for_volume(22, "text", 600, dark=True) is None

    def test_non_content_category_untouched(self):
        assert donor_map.upgrade_donor_for_volume(53, "table", 2000) is None

    def test_zero_volume_untouched(self):
        assert donor_map.upgrade_donor_for_volume(21, "text", 0) is None


class TestDesignNodeAppliesUpgrade:
    def _state(self, raw_body_chars: int):
        from schemas.session import SessionInput, SessionState
        inp = SessionInput(
            session_id="test-capacity", user_id=1, chat_id=1,
            progress_message_id=0, mode="verstai", input_s3_key=None,
        )
        s = SessionState.from_input(inp)
        brief = {
            "topic": "t", "slide_count": 1,
            "slides": [{
                "num": 1, "raw_title": "Заголовок",
                "raw_body": ["х" * raw_body_chars],
                "intent": "text",
            }],
        }
        classification = {"slides": [{
            "num": 1, "category": "text", "subcategory_hint": "",
            "rationale": "", "slide_type": None, "dark": False,
        }]}
        return s.model_copy(update={"artefacts": {
            "brief": brief, "classification": classification,
        }})

    def _run_design(self, monkeypatch, raw_body_chars: int) -> int:
        from graph.nodes import agents
        from schemas.slides import LayoutPlan
        plan = LayoutPlan.model_validate({"slides": [{
            "num": 1, "layout_idx": 21, "layout_name": "content_text_white",
            "rationale": "text slide",
        }]})
        monkeypatch.setattr(agents, "_emit", lambda *a, **k: None)
        monkeypatch.setattr(
            agents, "call_and_parse", lambda **kw: (plan, None))
        patch = agents.design_node(self._state(raw_body_chars))
        return patch["artefacts"]["layouts"]["slides"][0]["layout_idx"]

    def test_overloaded_pick_is_upgraded(self, monkeypatch):
        idx = self._run_design(monkeypatch, raw_body_chars=600)
        assert idx != 21
        assert donor_map.body_capacity(idx) >= 600

    def test_fitting_pick_is_kept(self, monkeypatch):
        assert self._run_design(monkeypatch, raw_body_chars=100) == 21
