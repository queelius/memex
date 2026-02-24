"""Tests for scripts framework discovery and CLI integration."""
import argparse
import types
from pathlib import Path
from unittest.mock import patch

import pytest

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
