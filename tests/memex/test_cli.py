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


class TestCLIHelp:
    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "memex" in result.stdout.lower()
