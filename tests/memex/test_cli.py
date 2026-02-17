"""Tests for memex CLI: import, export, serve, version."""
import json
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


class TestCLIHelp:
    def test_no_command_shows_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "memex"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower() or "memex" in result.stdout.lower()
