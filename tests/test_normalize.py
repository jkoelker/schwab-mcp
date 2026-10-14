"""Tests for result-payload normalization helpers."""

from __future__ import annotations

from schwab_mcp.tools.normalize import strip_noise


class TestStripNoise:
    def test_none_is_stripped_from_dict(self):
        assert strip_noise({"a": None}) == {}

    def test_empty_string_is_stripped_from_dict(self):
        assert strip_noise({"a": ""}) == {}

    def test_empty_list_is_kept_in_dict(self):
        # Empty lists are meaningful "known empty" results (e.g. candles: [],
        # positions: []), not absent fields, so they must survive stripping.
        assert strip_noise({"a": []}) == {"a": []}

    def test_empty_dict_is_stripped_from_dict(self):
        assert strip_noise({"a": {}}) == {}

    def test_zero_int_is_kept(self):
        assert strip_noise({"v": 0}) == {"v": 0}

    def test_zero_float_is_kept(self):
        assert strip_noise({"v": 0.0}) == {"v": 0.0}

    def test_false_is_kept(self):
        assert strip_noise({"inTheMoney": False}) == {"inTheMoney": False}

    def test_nonempty_string_is_kept(self):
        assert strip_noise({"s": "text"}) == {"s": "text"}

    def test_nonempty_list_is_kept(self):
        assert strip_noise({"l": [1]}) == {"l": [1]}

    def test_nonempty_dict_is_kept(self):
        assert strip_noise({"d": {"k": "v"}}) == {"d": {"k": "v"}}

    def test_none_items_stripped_from_list(self):
        assert strip_noise([None, 1, None]) == [1]

    def test_empty_string_items_stripped_from_list(self):
        assert strip_noise(["", "a", ""]) == ["a"]

    def test_empty_list_items_are_kept_in_list(self):
        assert strip_noise([[], [1], []]) == [[], [1], []]

    def test_empty_dict_items_stripped_from_list(self):
        assert strip_noise([{}, {"k": "v"}, {}]) == [{"k": "v"}]

    def test_scalar_passthrough(self):
        assert strip_noise(42) == 42
        assert strip_noise(3.14) == 3.14
        assert strip_noise(True) is True
        assert strip_noise("hello") == "hello"

    def test_nested_structure(self):
        data = {"a": None, "b": {"c": [], "d": 0}, "e": [1, None, ""]}
        result = strip_noise(data)
        # "a" -> None, stripped
        # "b" -> {"c": [] kept, "d": 0 kept} -> {"c": [], "d": 0}
        # "e" -> [1, None stripped, "" stripped] -> [1]
        assert result == {"b": {"c": [], "d": 0}, "e": [1]}

    def test_empty_list_survives_nested_stripping(self):
        # A tool result like {"candles": []} must remain intact end-to-end,
        # since it represents a confirmed-empty result, not a missing field.
        assert strip_noise({"candles": []}) == {"candles": []}
        assert strip_noise({"securitiesAccount": {"positions": []}}) == {"securitiesAccount": {"positions": []}}

    def test_inner_empty_after_strip_causes_outer_drop(self):
        # {"a": {"b": None}} -> inner becomes {} -> outer key "a" is dropped
        assert strip_noise({"a": {"b": None}}) == {}

    def test_list_of_dicts_with_noise(self):
        data = [{"x": 1, "y": None}, {"x": 0, "y": ""}]
        assert strip_noise(data) == [{"x": 1}, {"x": 0}]
