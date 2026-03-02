"""Tests for memex CLI: import, export, mcp, version, show."""
import json
import os
import subprocess
import sys


class TestCLIVersion:
    def test_version_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex", "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "0.1.0" in result.stdout


class TestCLIImport:
    def test_import_openai(self, tmp_path):
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Imported 1 conversation" in result.stdout

    def test_import_forced_format(self, tmp_path):
        db_dir = tmp_path / "db"
        export_file = tmp_path / "data.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file),
             "--format", "openai", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Imported 1 conversation" in result.stdout

    def test_import_no_importer(self, tmp_path):
        db_dir = tmp_path / "db"
        export_file = tmp_path / "unknown.json"
        export_file.write_text(json.dumps({"random": "data"}))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "no importer found" in result.stderr


class TestCLIImportClaudeCode:
    def test_import_claude_code(self, tmp_path):
        from memex.db import Database
        db_dir = tmp_path / "db"
        export_file = tmp_path / "session.jsonl"
        events = [
            {
                "type": "user", "uuid": "u1", "parentUuid": None,
                "sessionId": "sess-cli-test", "slug": "cli-test-session",
                "timestamp": "2026-02-18T10:00:00Z",
                "userType": "external", "isSidechain": False,
                "message": {"role": "user", "content": "Hello from CLI test"},
            },
            {
                "type": "assistant", "uuid": "a1", "parentUuid": "u1",
                "sessionId": "sess-cli-test", "slug": "cli-test-session",
                "timestamp": "2026-02-18T10:00:01Z",
                "userType": "external", "isSidechain": False,
                "message": {"role": "assistant", "model": "claude-opus-4-6",
                            "content": [{"type": "text", "text": "Hello!"}]},
            },
        ]
        export_file.write_text("\n".join(json.dumps(e) for e in events))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Imported 1 conversation" in result.stdout
        # Verify provenance was saved
        db = Database(str(db_dir))
        prov = db.get_provenance("sess-cli-test")
        assert len(prov) == 1
        assert prov[0]["source_type"] == "claude_code"
        db.close()


class TestCLIImportProvenance:
    def test_import_persists_provenance(self, tmp_path):
        from memex.db import Database
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Verify provenance was saved to DB
        db = Database(str(db_dir))
        prov = db.get_provenance("c1")
        assert len(prov) == 1
        assert prov[0]["source_type"] == "openai"
        assert prov[0]["source_id"] == "c1"
        assert str(export_file) in prov[0]["source_file"]
        db.close()


class TestCLIExport:
    def test_export_markdown(self, tmp_path):
        # First import, then export
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Exported Chat",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello world"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        # Import
        subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        # Export
        out_file = tmp_path / "out.md"
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", str(out_file),
             "--format", "markdown", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Exported 1 conversation" in result.stdout
        content = out_file.read_text()
        assert "hello world" in content

    def test_export_json(self, tmp_path):
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hi"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        out_file = tmp_path / "out.json"
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", str(out_file),
             "--format", "json", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(out_file.read_text())
        assert len(data) == 1
        assert data[0]["id"] == "c1"


class TestCLIShow:
    def _import_one(self, tmp_path):
        """Helper: import one conversation, return db_dir."""
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Show Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": ["m2"],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello world"]},
                        "create_time": 1700000000,
                    },
                },
                "m2": {
                    "id": "m2", "parent": "m1", "children": [],
                    "message": {
                        "id": "m2", "author": {"role": "assistant"},
                        "content": {"parts": ["hi there"]},
                        "create_time": 1700000001,
                        "metadata": {"model_slug": "gpt-4"},
                    },
                },
            },
        }]))
        subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        return db_dir

    def test_show_list(self, tmp_path):
        db_dir = self._import_one(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "memex", "show", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "c1" in result.stdout
        assert "Show Test" in result.stdout

    def test_show_conversation(self, tmp_path):
        db_dir = self._import_one(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "memex", "show", "c1", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "# Show Test" in result.stdout
        assert "hello world" in result.stdout
        assert "hi there" in result.stdout

    def test_show_not_found(self, tmp_path):
        db_dir = self._import_one(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "memex", "show", "nope", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "not found" in result.stderr


class TestCLIImportAssets:
    def test_import_with_assets(self, tmp_path):
        """Import OpenAI file with an image asset, verify it's copied and rendered."""
        from memex.db import Database

        db_dir = tmp_path / "db"
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # Create a fake image file matching the asset_pointer
        img_file = source_dir / "file-img001-photo.png"
        img_file.write_bytes(b"\x89PNG fake image data")

        # Create OpenAI export with an image asset_pointer
        export_file = source_dir / "conversations.json"
        export_file.write_text(json.dumps([{
            "id": "c-media", "title": "Media Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": ["m2"],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["check out this image"]},
                        "create_time": 1700000000,
                    },
                },
                "m2": {
                    "id": "m2", "parent": "m1", "children": [],
                    "message": {
                        "id": "m2", "author": {"role": "assistant"},
                        "content": {"parts": [
                            {"asset_pointer": "file-service://file-img001",
                             "content_type": "image_asset_pointer"},
                        ]},
                        "create_time": 1700000001,
                    },
                },
            },
        }]))

        result = subprocess.run(
            [sys.executable, "-m", "memex", "import",
             str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Imported 1 conversation" in result.stdout

        # Verify assets directory was created with the image
        assets_dir = db_dir / "assets"
        assert assets_dir.exists()
        asset_files = list(assets_dir.iterdir())
        assert len(asset_files) == 1
        assert asset_files[0].read_bytes() == b"\x89PNG fake image data"

        # Verify `memex show` renders the image as markdown
        show_result = subprocess.run(
            [sys.executable, "-m", "memex", "show", "c-media", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert show_result.returncode == 0
        assert "![" in show_result.stdout

    def test_import_no_copy_assets_flag(self, tmp_path):
        """--no-copy-assets skips asset copying."""
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file),
             "--no-copy-assets", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        # Assets directory should not exist (no media to copy, but flag works)
        assert not (db_dir / "assets").exists()


class TestCLIListFormats:
    def test_import_list_formats(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", "--list-formats"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Available import formats:" in result.stdout
        # Check all built-in importers are listed
        for name in ("openai", "anthropic", "gemini", "claude_code"):
            assert name in result.stdout

    def test_export_list_formats(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", "--list-formats"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Available export formats:" in result.stdout
        # Check all built-in exporters are listed (json_export.py → json)
        for name in ("json", "markdown", "html"):
            assert name in result.stdout

    def test_import_unknown_format_shows_available(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", "/dev/null",
             "--format", "nonexistent"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "unknown format" in result.stderr
        assert "openai" in result.stderr  # lists available formats

    def test_export_unknown_format_shows_available(self, tmp_path):
        db_dir = tmp_path / "db"
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", str(tmp_path / "out.txt"),
             "--format", "nonexistent", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "unknown export format" in result.stderr
        assert "json" in result.stderr  # lists available formats

    def test_import_list_formats_without_file(self):
        """--list-formats should work without providing a file argument."""
        result = subprocess.run(
            [sys.executable, "-m", "memex", "import", "--list-formats"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Available import formats:" in result.stdout

    def test_export_list_formats_without_output(self):
        """--list-formats should work without providing an output argument."""
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", "--list-formats"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "Available export formats:" in result.stdout


class TestDiscoverFormats:
    """Unit tests for _discover_formats, _discover_importers, _discover_exporters."""

    def test_discover_importers_returns_all_builtins(self):
        from memex.cli import _discover_importers
        importers = _discover_importers()
        assert "openai" in importers
        assert "anthropic" in importers
        assert "gemini" in importers
        assert "claude_code" in importers

    def test_discover_importers_have_descriptions(self):
        from memex.cli import _discover_importers
        importers = _discover_importers()
        for name, info in importers.items():
            assert info["description"], f"Importer {name} has no description"

    def test_discover_exporters_returns_all_builtins(self):
        from memex.cli import _discover_exporters
        exporters = _discover_exporters()
        assert "json" in exporters
        assert "markdown" in exporters
        assert "html" in exporters

    def test_discover_exporters_strips_suffix(self):
        """json_export.py should be discovered as 'json', not 'json_export'."""
        from memex.cli import _discover_exporters
        exporters = _discover_exporters()
        assert "json" in exporters
        assert "json_export" not in exporters

    def test_discover_exporters_have_descriptions(self):
        from memex.cli import _discover_exporters
        exporters = _discover_exporters()
        for name, info in exporters.items():
            assert info["description"], f"Exporter {name} has no description"

    def test_discover_formats_skips_underscored_files(self):
        from memex.cli import _discover_importers
        importers = _discover_importers()
        # __init__.py should not appear
        assert "__init__" not in importers

    def test_user_plugin_directory(self, tmp_path, monkeypatch):
        """User plugins from ~/.memex/importers/ are discovered."""
        from memex.cli import _discover_formats
        user_dir = tmp_path / "user_importers"
        user_dir.mkdir()
        # Write a minimal importer plugin
        plugin = user_dir / "custom.py"
        plugin.write_text(
            '"""Custom test importer."""\n'
            'def detect(f): return False\n'
            'def import_file(f): return []\n'
        )
        builtin_dir = tmp_path / "empty_builtins"
        builtin_dir.mkdir()
        formats = _discover_formats(builtin_dir, user_dir, ("detect", "import_file"))
        assert "custom" in formats
        assert "Custom test importer." in formats["custom"]["description"]


class TestCLIHelp:
    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "memex" in result.stdout.lower()
