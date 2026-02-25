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


# ── Mutation Engine ─────────────────────────────────────────────


class TestRedactWordLevel:
    def test_replaces_match(self):
        from memex.scripts.redact import Match, redact_word_level
        content = [{"type": "text", "text": "what the fuck"}]
        matches = [Match("c1", "m1", "fuck", 9, 13, 0)]
        result = redact_word_level(content, matches)
        assert result[0]["text"] == "what the [REDACTED]"

    def test_preserves_non_text_blocks(self):
        from memex.scripts.redact import Match, redact_word_level
        content = [{"type": "text", "text": "fuck"}, {"type": "tool_use", "id": "x"}]
        matches = [Match("c1", "m1", "fuck", 0, 4, 0)]
        result = redact_word_level(content, matches)
        assert result[1] == {"type": "tool_use", "id": "x"}

    def test_multiple_matches_in_block(self):
        from memex.scripts.redact import Match, redact_word_level
        content = [{"type": "text", "text": "fuck this shit"}]
        matches = [Match("c1", "m1", "fuck", 0, 4, 0), Match("c1", "m1", "shit", 10, 14, 0)]
        result = redact_word_level(content, matches)
        assert result[0]["text"] == "[REDACTED] this [REDACTED]"

    def test_does_not_mutate_original(self):
        from memex.scripts.redact import Match, redact_word_level
        content = [{"type": "text", "text": "fuck"}]
        matches = [Match("c1", "m1", "fuck", 0, 4, 0)]
        redact_word_level(content, matches)
        assert content[0]["text"] == "fuck"  # original unchanged


class TestRedactMessageLevel:
    def test_replaces_entire_content(self):
        from memex.scripts.redact import redact_message_level
        result = redact_message_level()
        assert result == [{"type": "text", "text": "[REDACTED]"}]


class TestRunDryRun:
    def test_reports_but_no_changes(self, tmp_db_path):
        """Dry run shows matches but doesn't modify DB."""
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("what the fuck")
        db.save_conversation(conv)
        args = _make_args(words="fuck", level="word")
        stats = run(db, args, apply=False)
        assert stats["word_redactions"] > 0
        # DB unchanged
        reloaded = db.load_conversation("c1")
        assert "fuck" in reloaded.messages["m1"].get_text()
        db.close()


class TestRunApplyBatch:
    def test_word_level(self, tmp_db_path):
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("what the fuck")
        db.save_conversation(conv)
        args = _make_args(words="fuck", level="word", yes=True)
        stats = run(db, args, apply=True)
        reloaded = db.load_conversation("c1")
        assert "[REDACTED]" in reloaded.messages["m1"].get_text()
        # Original stored as enrichment
        enrichments = db.get_enrichments("c1")
        originals = [e for e in enrichments if e["type"] == "original_content"]
        assert len(originals) == 1
        db.close()

    def test_message_level(self, tmp_db_path):
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("what the fuck")
        db.save_conversation(conv)
        args = _make_args(words="fuck", level="message", yes=True)
        run(db, args, apply=True)
        reloaded = db.load_conversation("c1")
        assert reloaded.messages["m1"].get_text() == "[REDACTED]"
        db.close()

    def test_conversation_level(self, tmp_db_path):
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("what the fuck")
        db.save_conversation(conv)
        args = _make_args(words="fuck", level="conversation", yes=True)
        run(db, args, apply=True)
        assert db.load_conversation("c1") is None
        db.close()

    def test_all_mode(self, tmp_db_path):
        """--all requires every term to match."""
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("just drunk")
        db.save_conversation(conv)
        args = _make_args(words="drunk,kim", level="message", yes=True, all_mode=True)
        run(db, args, apply=True)
        # "kim" not present, so no redaction
        reloaded = db.load_conversation("c1")
        assert "drunk" in reloaded.messages["m1"].get_text()
        db.close()

    def test_no_matches_returns_zero_stats(self, tmp_db_path):
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("perfectly clean text")
        db.save_conversation(conv)
        args = _make_args(words="profanity", level="word", yes=True)
        stats = run(db, args, apply=True)
        assert stats["word_redactions"] == 0
        db.close()


# ── Interactive Review ──────────────────────────────────────────


class TestInteractiveMode:
    def _setup_conv(self, tmp_db_path, text="what the fuck"):
        from memex.scripts.redact import compile_matchers, scan_message, ScanResult
        db = Database(tmp_db_path)
        conv = _make_conv_with_text(text)
        db.save_conversation(conv)
        return db

    def test_redact_choice(self, tmp_db_path):
        """'r' redacts the match."""
        from memex.scripts.redact import interactive_review, compile_matchers, scan_message
        db = self._setup_conv(tmp_db_path)
        matchers = compile_matchers(words=["fuck"])
        content = [{"type": "text", "text": "what the fuck"}]
        result = scan_message(content, matchers, "c1", "m1")
        responses = iter(["r"])
        stats = interactive_review([result], db, "word", input_fn=lambda _: next(responses))
        assert stats["redacted"] == 1
        reloaded = db.load_conversation("c1")
        assert "[REDACTED]" in reloaded.messages["m1"].get_text()
        db.close()

    def test_skip_choice(self, tmp_db_path):
        """'s' skips without modifying."""
        from memex.scripts.redact import interactive_review, compile_matchers, scan_message
        db = self._setup_conv(tmp_db_path)
        matchers = compile_matchers(words=["fuck"])
        content = [{"type": "text", "text": "what the fuck"}]
        result = scan_message(content, matchers, "c1", "m1")
        responses = iter(["s"])
        stats = interactive_review([result], db, "word", input_fn=lambda _: next(responses))
        assert stats["skipped"] == 1
        reloaded = db.load_conversation("c1")
        assert "fuck" in reloaded.messages["m1"].get_text()
        db.close()

    def test_quit_stops_early(self, tmp_db_path):
        """'q' stops and returns what's been done."""
        from memex.scripts.redact import interactive_review, compile_matchers, scan_message
        db = Database(tmp_db_path)
        # Two conversations with profanity
        conv1 = _make_conv_with_text("what the fuck", id="c1")
        conv2 = _make_conv_with_text("oh shit", id="c2")
        db.save_conversation(conv1)
        db.save_conversation(conv2)
        matchers = compile_matchers(words=["fuck", "shit"])
        result1 = scan_message([{"type": "text", "text": "what the fuck"}], matchers, "c1", "m1")
        result2 = scan_message([{"type": "text", "text": "oh shit"}], matchers, "c2", "m1")
        responses = iter(["r", "q"])
        stats = interactive_review([result1, result2], db, "word",
                                   input_fn=lambda _: next(responses))
        assert stats["redacted"] == 1
        # First redacted, second untouched
        r1 = db.load_conversation("c1")
        assert "[REDACTED]" in r1.messages["m1"].get_text()
        r2 = db.load_conversation("c2")
        assert "shit" in r2.messages["m1"].get_text()
        db.close()

    def test_all_choice_auto_redacts(self, tmp_db_path):
        """'a' redacts this and all same-term matches."""
        from memex.scripts.redact import interactive_review, compile_matchers, scan_message
        db = Database(tmp_db_path)
        conv1 = _make_conv_with_text("what the fuck", id="c1")
        conv2 = _make_conv_with_text("oh fuck again", id="c2")
        db.save_conversation(conv1)
        db.save_conversation(conv2)
        matchers = compile_matchers(words=["fuck"])
        result1 = scan_message([{"type": "text", "text": "what the fuck"}], matchers, "c1", "m1")
        result2 = scan_message([{"type": "text", "text": "oh fuck again"}], matchers, "c2", "m1")
        # Only prompted once — 'a' auto-applies to second
        responses = iter(["a"])
        stats = interactive_review([result1, result2], db, "word",
                                   input_fn=lambda _: next(responses))
        assert stats["redacted"] == 2
        r1 = db.load_conversation("c1")
        assert "[REDACTED]" in r1.messages["m1"].get_text()
        r2 = db.load_conversation("c2")
        assert "[REDACTED]" in r2.messages["m1"].get_text()
        db.close()

    def test_message_level_interactive(self, tmp_db_path):
        """Interactive mode works for message-level redaction."""
        from memex.scripts.redact import interactive_review, compile_matchers, scan_message
        db = self._setup_conv(tmp_db_path)
        matchers = compile_matchers(words=["fuck"])
        content = [{"type": "text", "text": "what the fuck"}]
        result = scan_message(content, matchers, "c1", "m1")
        responses = iter(["r"])
        stats = interactive_review([result], db, "message", input_fn=lambda _: next(responses))
        assert stats["redacted"] == 1
        reloaded = db.load_conversation("c1")
        assert reloaded.messages["m1"].get_text() == "[REDACTED]"
        db.close()

    def test_run_interactive_via_apply_no_yes(self, tmp_db_path):
        """run() with apply=True, yes=False triggers interactive review."""
        from memex.scripts.redact import run
        db = Database(tmp_db_path)
        conv = _make_conv_with_text("what the fuck")
        db.save_conversation(conv)
        args = _make_args(words="fuck", level="word", yes=False)
        # Patch input to auto-respond 'r'
        with patch("memex.scripts.redact.interactive_review") as mock_review:
            mock_review.return_value = {"redacted": 1, "skipped": 0}
            stats = run(db, args, apply=True)
            assert mock_review.called
        db.close()


# ── Built-in Pattern Files ──────────────────────────────────────


class TestBuiltinPatterns:
    def test_api_keys_file_exists(self):
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "memex" / "scripts" / "patterns" / "api_keys.txt"
        assert p.exists()

    def test_pii_file_exists(self):
        from pathlib import Path
        p = Path(__file__).parent.parent.parent / "memex" / "scripts" / "patterns" / "pii.txt"
        assert p.exists()

    def test_api_keys_matches_openai(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="api_keys.txt")
        assert any(m[0].search("sk-proj-abc123def456ghi789jkl012mno") for m in matchers)

    def test_api_keys_matches_github(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="api_keys.txt")
        assert any(m[0].search("ghp_ABCDEFghijklmnopqrstuvwxyz0123456789") for m in matchers)

    def test_api_keys_matches_aws(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="api_keys.txt")
        assert any(m[0].search("AKIAIOSFODNN7EXAMPLE") for m in matchers)

    def test_pii_matches_email(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="pii.txt")
        assert any(m[0].search("user@example.com") for m in matchers)

    def test_pii_matches_phone(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="pii.txt")
        assert any(m[0].search("555-123-4567") for m in matchers)

    def test_pii_matches_ssn(self):
        from memex.scripts.redact import compile_matchers
        matchers = compile_matchers(pattern_file="pii.txt")
        assert any(m[0].search("123-45-6789") for m in matchers)

    def test_load_via_bare_filename(self):
        """Bare filename resolves to built-in patterns/ dir."""
        from memex.scripts.redact import load_pattern_file
        patterns = load_pattern_file("api_keys.txt")
        assert len(patterns) >= 3  # at least OpenAI, GitHub, AWS
