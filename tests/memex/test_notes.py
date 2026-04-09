"""Tests for the notes feature (schema v4 marginalia)."""
import os
import sqlite3
import subprocess
import sys

import pytest

from memex.db import Database, SCHEMA_VERSION


class TestSchemaV4:
    def test_schema_version_is_4(self):
        assert SCHEMA_VERSION == 4

    def test_fresh_database_has_notes_table(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        tables = {
            r["name"]
            for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "notes" in tables
        db.close()

    def test_fresh_database_has_notes_fts(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        # FTS5 virtual tables appear in sqlite_master with type='table'
        tables = {
            r["name"]
            for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "notes_fts" in tables
        db.close()

    def test_fresh_database_has_notes_indexes(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        indexes = {
            r["name"]
            for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_notes_target" in indexes
        assert "idx_notes_kind" in indexes
        db.close()

    def test_notes_column_shape(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        cols = {
            r["name"]: r["type"]
            for r in db.conn.execute("PRAGMA table_info(notes)").fetchall()
        }
        assert "id" in cols
        assert "target_kind" in cols
        assert "conversation_id" in cols
        assert "message_id" in cols
        assert "text" in cols
        assert "created_at" in cols
        assert "updated_at" in cols
        db.close()
