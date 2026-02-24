"""Tests for scripts framework discovery and CLI integration."""
import argparse
import json
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from memex.db import Database
from memex.models import Conversation, Message, text_block
from memex.scripts import discover_scripts, load_script


class TestScriptDiscovery:
    def test_discover_finds_builtin_scripts(self, tmp_path):
        """Scripts in the built-in dir are discovered."""
        script = tmp_path / "hello.py"
        script.write_text(
            '"""Say hello."""\n'
            'def register_args(parser): pass\n'
            'def run(db, args, apply=False): return {}\n'
        )
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                scripts = discover_scripts()
        assert "hello" in scripts
        assert scripts["hello"]["description"] == "Say hello."

    def test_discover_skips_underscore_files(self, tmp_path):
        """Files starting with _ are skipped."""
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "_utils.py").write_text(
            '"""Private."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                scripts = discover_scripts()
        assert len(scripts) == 0

    def test_discover_user_scripts(self, tmp_path):
        """User scripts in ~/.memex/scripts/ are discovered."""
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        user = tmp_path / "user"
        user.mkdir()
        (user / "custom.py").write_text(
            '"""Custom script."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        with patch("memex.scripts._builtin_dir", return_value=builtin):
            with patch("memex.scripts._user_dir", return_value=user):
                scripts = discover_scripts()
        assert "custom" in scripts

    def test_load_script_returns_module(self, tmp_path):
        """load_script returns a module with the convention interface."""
        (tmp_path / "example.py").write_text(
            '"""Example."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {"ok": True}'
        )
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                mod = load_script("example")
        assert hasattr(mod, "register_args")
        assert hasattr(mod, "run")

    def test_load_script_not_found_raises(self, tmp_path):
        """load_script raises ValueError for unknown scripts."""
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                with pytest.raises(ValueError, match="not found"):
                    load_script("nonexistent")

    def test_user_shadows_builtin(self, tmp_path):
        """User script with same name shadows built-in."""
        builtin = tmp_path / "builtin"
        builtin.mkdir()
        user = tmp_path / "user"
        user.mkdir()
        (builtin / "dupe.py").write_text(
            '"""Built-in."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        (user / "dupe.py").write_text(
            '"""User version."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        with patch("memex.scripts._builtin_dir", return_value=builtin):
            with patch("memex.scripts._user_dir", return_value=user):
                scripts = discover_scripts()
        assert scripts["dupe"]["description"] == "User version."

    def test_discover_skips_invalid_modules(self, tmp_path):
        """Modules without required interface are skipped."""
        (tmp_path / "broken.py").write_text(
            '"""No interface."""\ndef something(): pass\n'
        )
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                scripts = discover_scripts()
        assert len(scripts) == 0


class TestCLIRun:
    """CLI tests use _cmd_run directly to avoid _get_version import issue
    (tests/memex/__init__.py shadows the real memex package)."""

    def test_run_list(self, tmp_path, capsys):
        """memex run --list shows available scripts."""
        from memex.cli import _cmd_run
        (tmp_path / "hello.py").write_text(
            '"""Say hello."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        args = argparse.Namespace(name=None, list=True, apply=False, verbose=False,
                                  db=str(tmp_path))
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                _cmd_run(args, [])
        out = capsys.readouterr().out
        assert "hello" in out
        assert "Say hello." in out

    def test_run_no_name_shows_list(self, tmp_path, capsys):
        """memex run without name shows available scripts or 'no scripts'."""
        from memex.cli import _cmd_run
        (tmp_path / "hello.py").write_text(
            '"""Say hello."""\ndef register_args(p): pass\ndef run(d,a,apply=False): return {}'
        )
        args = argparse.Namespace(name=None, list=False, apply=False, verbose=False,
                                  db=str(tmp_path))
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                _cmd_run(args, [])
        out = capsys.readouterr().out
        assert "Available scripts" in out

    def test_run_unknown_errors(self, tmp_path, capsys):
        """memex run nonexistent prints error and exits."""
        from memex.cli import _cmd_run
        args = argparse.Namespace(name="nonexistent", list=False, apply=False,
                                  verbose=False, db=str(tmp_path))
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                with pytest.raises(SystemExit):
                    _cmd_run(args, [])

    def test_run_executes_script(self, tmp_path, capsys):
        """memex run <name> executes the script's run function."""
        from memex.cli import _cmd_run
        (tmp_path / "hello.py").write_text(
            '"""Say hello."""\n'
            'def register_args(p): pass\n'
            'def run(db, args, apply=False):\n'
            '    print("hello from script")\n'
            '    return {}\n'
        )
        db_dir = tmp_path / "testdb"
        db_dir.mkdir()
        args = argparse.Namespace(name="hello", list=False, apply=False,
                                  verbose=False, db=str(db_dir))
        with patch("memex.scripts._builtin_dir", return_value=tmp_path):
            with patch("memex.scripts._user_dir", return_value=tmp_path / "nope"):
                _cmd_run(args, [])
        out = capsys.readouterr().out
        assert "hello from script" in out


def _make_conv(id="c1", title="Test", msg_text="hello"):
    now = datetime.now()
    conv = Conversation(id=id, created_at=now, updated_at=now, title=title,
                        source="test", model="gpt-4")
    conv.add_message(Message(id="m1", role="user", content=[text_block(msg_text)]))
    return conv


class TestEnrichTrivialScript:
    def test_has_convention_interface(self):
        mod = load_script("enrich_trivial")
        assert hasattr(mod, "register_args")
        assert hasattr(mod, "run")
        assert mod.__doc__

    def test_dry_run_returns_stats(self, tmp_db_path):
        """Dry run scans but doesn't write."""
        db = Database(tmp_db_path)
        conv = _make_conv(msg_text="hi")
        conv.message_count = 1
        db.save_conversation(conv)
        db.close()

        db = Database(tmp_db_path, readonly=True)
        mod = load_script("enrich_trivial")
        script_args = argparse.Namespace(max_messages=4)
        stats = mod.run(db, script_args, apply=False)
        assert stats["greeting"] >= 0  # returns stats dict
        # DB unchanged — no enrichments
        db.close()
        db = Database(tmp_db_path, readonly=True)
        enrichments = db.get_enrichments("c1")
        assert len(enrichments) == 0
        db.close()

    def test_apply_writes_enrichments(self, tmp_db_path):
        """Apply mode writes enrichments to DB."""
        db = Database(tmp_db_path)
        # Empty conversation (0 messages) — trivial with confidence 1.0
        now = datetime.now()
        conv = Conversation(id="empty1", created_at=now, updated_at=now,
                            title="Empty", message_count=0, source="test")
        db.save_conversation(conv)

        mod = load_script("enrich_trivial")
        script_args = argparse.Namespace(max_messages=4)
        stats = mod.run(db, script_args, apply=True)
        assert stats["trivial"] >= 1

        enrichments = db.get_enrichments("empty1")
        importance_vals = [e for e in enrichments if e["type"] == "importance"]
        assert len(importance_vals) == 1
        assert importance_vals[0]["value"] == "trivial"
        db.close()
