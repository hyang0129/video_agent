"""Unit tests for src/utils/json_utils.py."""

import json
import pytest

from src.utils.json_utils import extract_json_object, safe_json_loads


class TestExtractJsonObject:
    """Tests for extract_json_object."""

    def test_plain_object(self):
        result = extract_json_object('{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_plain_array(self):
        result = extract_json_object('[1, 2, 3]')
        assert result == '[1, 2, 3]'

    def test_object_with_preamble(self):
        result = extract_json_object('Here is the data: {"key": "value"} done')
        assert json.loads(result) == {"key": "value"}

    def test_array_with_preamble(self):
        result = extract_json_object('Result: [1, 2, 3]')
        assert json.loads(result) == [1, 2, 3]

    def test_markdown_json_code_block(self):
        text = "```json\n{\"key\": \"value\"}\n```"
        result = extract_json_object(text)
        assert json.loads(result) == {"key": "value"}

    def test_markdown_plain_code_block(self):
        text = "```\n{\"key\": \"value\"}\n```"
        result = extract_json_object(text)
        assert json.loads(result) == {"key": "value"}

    def test_empty_string_returns_none(self):
        assert extract_json_object("") is None

    def test_no_json_returns_none(self):
        assert extract_json_object("just plain text") is None

    def test_object_preferred_over_array_when_object_comes_first(self):
        result = extract_json_object('{"a": 1} [2, 3]')
        assert json.loads(result) == {"a": 1}


class TestSafeJsonLoads:
    """Tests for safe_json_loads."""

    def test_valid_json(self):
        assert safe_json_loads('{"key": "value"}') == {"key": "value"}

    def test_valid_json_array(self):
        assert safe_json_loads('[1, 2, 3]') == [1, 2, 3]

    def test_json_with_preamble(self):
        assert safe_json_loads('prefix {"key": "value"} suffix') == {"key": "value"}

    def test_markdown_code_block(self):
        text = "```json\n{\"answer\": 42}\n```"
        assert safe_json_loads(text) == {"answer": 42}

    def test_raises_on_unparseable_text(self):
        with pytest.raises(json.JSONDecodeError):
            safe_json_loads("this is not json at all")
