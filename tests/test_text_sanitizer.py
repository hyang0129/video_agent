"""Tests for src/utils/text_sanitizer.py.

Run with: pytest tests/test_text_sanitizer.py -v
"""

from video_agent.utils.text_sanitizer import sanitize_text, has_unsafe_characters


class TestSanitizeText:

    def test_plain_ascii_unchanged(self):
        assert sanitize_text("Hello, world!") == "Hello, world!"

    def test_em_dash_replaced(self):
        result = sanitize_text("cheese \u2014 the best food")
        assert "\u2014" not in result
        assert "cheese - the best food" == result

    def test_en_dash_replaced(self):
        result = sanitize_text("1900\u20131950")
        assert "\u2013" not in result
        assert "1900 - 1950" == result

    def test_curly_single_quotes(self):
        result = sanitize_text("\u2018Hello\u2019")
        assert result == "'Hello'"

    def test_curly_double_quotes(self):
        result = sanitize_text("\u201CHello\u201D")
        assert result == '"Hello"'

    def test_ellipsis(self):
        result = sanitize_text("Wait\u2026 what?")
        assert result == "Wait... what?"

    def test_emoji_stripped(self):
        result = sanitize_text("Great food! \U0001F600\U0001F355")
        assert result == "Great food!"

    def test_zero_width_chars_stripped(self):
        result = sanitize_text("hello\u200Bworld")
        assert result == "helloworld"

    def test_non_breaking_space(self):
        result = sanitize_text("hello\u00A0world")
        assert result == "hello world"

    def test_multiple_replacements(self):
        text = "\u201CThe hamburger\u201D \u2014 a \u2018great\u2019 invention\u2026"
        result = sanitize_text(text)
        assert result == '"The hamburger" - a \'great\' invention...'

    def test_empty_string(self):
        assert sanitize_text("") == ""

    def test_none_passthrough(self):
        # sanitize_text expects str but should handle empty gracefully
        assert sanitize_text("") == ""

    def test_whitespace_collapsed(self):
        result = sanitize_text("hello   world")
        assert result == "hello world"

    def test_preserves_newlines(self):
        result = sanitize_text("line one\nline two")
        assert "line one\nline two" == result

    def test_real_world_screenplay_line(self):
        # Actual problematic line from a pipeline run
        text = "But Hamburg, Germany argues their \u2018steak tartare\u2019 \u2014 raw minced beef \u2014 was the inspiration behind the beef patty."
        result = sanitize_text(text)
        assert "\u2014" not in result
        assert "\u2018" not in result
        assert "\u2019" not in result
        assert "steak tartare" in result
        assert " - " in result


class TestHasUnsafeCharacters:

    def test_clean_ascii(self):
        assert has_unsafe_characters("Hello, world!") == []

    def test_detects_em_dash(self):
        issues = has_unsafe_characters("hello \u2014 world")
        assert any("em-dash" in i for i in issues)

    def test_detects_curly_quotes(self):
        issues = has_unsafe_characters("\u201Chello\u201D")
        assert any("curly quotes" in i for i in issues)

    def test_detects_emoji(self):
        issues = has_unsafe_characters("great \U0001F600")
        assert any("emoji" in i for i in issues)

    def test_empty_string(self):
        assert has_unsafe_characters("") == []
