"""Tests for the redact script — detection, mutation, and interactive review."""
import argparse
import json
from datetime import datetime
from unittest.mock import patch

import pytest

from memex.db import Database
from memex.models import Conversation, Message, text_block


def _make_conv_with_text(text, id="c1", title="Test"):
    now = datetime.now()
    conv = Conversation(id=id, created_at=now, updated_at=now, title=title,
                        source="test", message_count=1)
    conv.add_message(Message(id="m1", role="user", content=[text_block(text)]))
    return conv


def _make_args(words=None, patterns=None, pattern_file=None, level="word",
               yes=False, all_mode=False):
    return argparse.Namespace(
        words=words, patterns=patterns, pattern_file=pattern_file,
        level=level, yes=yes, match_mode="all" if all_mode else "any",
    )


# ── Detection Engine ────────────────────────────────────────────


class TestCompileMatchers:
    def test_words_case_insensitive(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(words=["fuck"])
        assert matchers[0][0].search("What the Fuck")

    def test_words_word_boundary(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(words=["ass"])
        assert matchers[0][0].search("what an ass")
        assert not matchers[0][0].search("class method")

    def test_patterns_regex(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(patterns=[r"sk-[a-zA-Z0-9]{20,}"])
        assert matchers[0][0].search("key: sk-abc123def456ghi789jkl0")

    def test_combined(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(words=["bad"], patterns=[r"\d{3}-\d{4}"])
        assert len(matchers) == 2

    def test_empty_raises(self):
        from memex.scripts.redact import compile_matchers
        with pytest.raises(ValueError):
            compile_matchers()


class TestLoadPatternFile:
    def test_loads_patterns(self, tmp_path):
        from memex.scripts.redact import load_pattern_file
        f = tmp_path / "test.txt"
        f.write_text("pattern1\npattern2\n")
        patterns = load_pattern_file(str(f))
        assert len(patterns) == 2

    def test_skips_comments_and_blanks(self, tmp_path):
        from memex.scripts.redact import load_pattern_file
        f = tmp_path / "test.txt"
        f.write_text("# comment\n\npattern1\n  # indented comment\n")
        patterns = load_pattern_file(str(f))
        assert len(patterns) == 1


class TestScanMessage:
    def test_finds_word_in_text_block(self):
        from memex.scripts.redact import compile_matchers, scan_message
        content = [{"type": "text", "text": "what the fuck"}]
        matchers = compile_matchers(words=["fuck"])
        result = scan_message(content, matchers, "c1", "m1")
        assert len(result.matches) == 1
        assert result.matches[0].start == 9
        assert result.matches[0].end == 13

    def test_skips_non_text_blocks(self):
        from memex.scripts.redact import compile_matchers, scan_message
        content = [{"type": "tool_use", "name": "fuck"}]
        matchers = compile_matchers(words=["fuck"])
        result = scan_message(content, matchers, "c1", "m1")
        assert len(result.matches) == 0

    def test_multiple_matches(self):
        from memex.scripts.redact import compile_matchers, scan_message
        content = [{"type": "text", "text": "fuck this shit"}]
        matchers = compile_matchers(words=["fuck", "shit"])
        result = scan_message(content, matchers, "c1", "m1")
        assert len(result.matches) == 2

    def test_multiple_blocks(self):
        from memex.scripts.redact import compile_matchers, scan_message
        content = [
            {"type": "text", "text": "clean text"},
            {"type": "text", "text": "has fuck in it"},
        ]
        matchers = compile_matchers(words=["fuck"])
        result = scan_message(content, matchers, "c1", "m1")
        assert len(result.matches) == 1
        assert result.matches[0].block_index == 1


class TestMatchMode:
    def test_any_single_match(self):
        from memex.scripts.redact import compile_matchers, scan_message, check_match_mode
        content = [{"type": "text", "text": "just fuck"}]
        matchers = compile_matchers(words=["fuck", "shit"])
        result = scan_message(content, matchers, "c1", "m1")
        assert check_match_mode(result.matches, "any", matchers) is True

    def test_all_requires_every_matcher(self):
        from memex.scripts.redact import compile_matchers, scan_message, check_match_mode
        content = [{"type": "text", "text": "just fuck"}]
        matchers = compile_matchers(words=["fuck", "shit"])
        result = scan_message(content, matchers, "c1", "m1")
        assert check_match_mode(result.matches, "all", matchers) is False

    def test_all_all_match(self):
        from memex.scripts.redact import compile_matchers, scan_message, check_match_mode
        content = [{"type": "text", "text": "fuck this shit"}]
        matchers = compile_matchers(words=["fuck", "shit"])
        result = scan_message(content, matchers, "c1", "m1")
        assert check_match_mode(result.matches, "all", matchers) is True
