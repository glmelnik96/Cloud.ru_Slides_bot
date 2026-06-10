"""A1: deterministic column balancing for colN_body slots.

The Distributor LLM often skews items across column-body slots (donor 28
style: col1_body/col2_body[/col3_body] hold one continuous list split into
columns). ``_rebalance_column_bodies`` re-splits the combined items by word
volume, in order, when the distribution is visibly skewed. Paired layouts
(sub1+body1 etc.) do not match the col-body pattern and are never touched.
"""
from __future__ import annotations

from worker import skill_bridge

skill_bridge.install()

from build_v9 import _rebalance_column_bodies  # noqa: E402


def test_skewed_two_columns_rebalanced():
    slots = {
        "title": "Заголовок",
        "col1_body": "Один пункт\nВторой пункт\nТретий пункт\nЧетвёртый пункт\nПятый пункт",
        "col2_body": "Шестой",
    }
    out = _rebalance_column_bodies(slots)
    c1 = out["col1_body"].split("\n")
    c2 = out["col2_body"].split("\n")
    # All six items survive, order preserved across col1→col2.
    assert c1 + c2 == [
        "Один пункт", "Второй пункт", "Третий пункт",
        "Четвёртый пункт", "Пятый пункт", "Шестой",
    ]
    # Roughly even: neither column holds 5 of 6 items any more.
    assert 2 <= len(c1) <= 4
    assert 2 <= len(c2) <= 4
    # Non-column slots untouched.
    assert out["title"] == "Заголовок"


def test_balanced_columns_left_alone():
    slots = {
        "col1_body": "Пункт один\nПункт два",
        "col2_body": "Пункт три\nПункт четыре",
    }
    out = _rebalance_column_bodies(slots)
    assert out["col1_body"] == slots["col1_body"]
    assert out["col2_body"] == slots["col2_body"]


def test_single_column_untouched():
    slots = {"col1_body": "Один\nДва\nТри"}
    out = _rebalance_column_bodies(slots)
    assert out == slots


def test_empty_column_gets_items():
    slots = {
        "col1_body": "Первый пункт списка\nВторой пункт списка\nТретий пункт списка\nЧетвёртый пункт",
        "col2_body": "",
    }
    out = _rebalance_column_bodies(slots)
    assert out["col2_body"].strip(), "empty column must receive items"
    items = [l for v in (out["col1_body"], out["col2_body"]) for l in v.split("\n") if l]
    assert len(items) == 4


def test_fewer_items_than_columns_untouched():
    slots = {
        "col1_body": "Единственный пункт",
        "col2_body": "",
        "col3_body": "",
    }
    out = _rebalance_column_bodies(slots)
    assert out == slots


def test_non_string_values_skip_group():
    slots = {"col1_body": ["list", "value"], "col2_body": "Текст\nЕщё"}
    out = _rebalance_column_bodies(slots)
    assert out == slots


def test_three_columns_rebalanced_in_order():
    items = [f"Пункт номер {i} с одинаковым объёмом текста" for i in range(1, 10)]
    slots = {
        "col1_body": "\n".join(items),
        "col2_body": "",
        "col3_body": "",
    }
    out = _rebalance_column_bodies(slots)
    cols = [out[f"col{i}_body"].split("\n") for i in (1, 2, 3)]
    flat = [l for col in cols for l in col if l]
    assert flat == items, "order must be preserved"
    assert all(2 <= len([l for l in col if l]) <= 4 for col in cols)
