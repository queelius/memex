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


class TestSchemaV4EnrichmentMigration:
    def test_v3_enrichment_notes_move_to_notes_table(self, tmp_path):
        """Enrichment note rows at v3 must migrate into notes table at v4."""
        db_dir = tmp_path / "testdb"
        db_dir.mkdir()
        db_path = str(db_dir / "conversations.db")

        # Build a minimal v3-shaped database manually
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT, source TEXT, model TEXT, summary TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                starred_at DATETIME, pinned_at DATETIME, archived_at DATETIME,
                parent_conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                sensitive BOOLEAN NOT NULL DEFAULT 0,
                metadata JSON NOT NULL DEFAULT '{}'
            );
            CREATE TABLE messages (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                id TEXT NOT NULL, role TEXT NOT NULL, parent_id TEXT, model TEXT,
                created_at DATETIME, sensitive BOOLEAN NOT NULL DEFAULT 0,
                content JSON NOT NULL, metadata JSON NOT NULL DEFAULT '{}',
                PRIMARY KEY (conversation_id, id)
            );
            CREATE TABLE tags (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                tag TEXT NOT NULL, PRIMARY KEY (conversation_id, tag)
            );
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                conversation_id UNINDEXED, message_id UNINDEXED, text,
                tokenize = 'porter unicode61'
            );
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            CREATE TABLE enrichments (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                type TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
                confidence REAL, created_at DATETIME NOT NULL,
                PRIMARY KEY (conversation_id, type, value)
            );
            CREATE TABLE provenance (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL, source_file TEXT, source_id TEXT,
                source_hash TEXT, imported_at DATETIME NOT NULL, importer_version TEXT,
                PRIMARY KEY (conversation_id, source_type)
            );
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2025-01-01 00:00:00', '2025-01-01 00:00:00')"
        )
        conn.execute(
            "INSERT INTO enrichments (conversation_id, type, value, source, created_at) "
            "VALUES ('c1', 'note', 'an important thought', 'user', '2025-01-01 00:00:00')"
        )
        conn.commit()
        conn.close()

        # Open via Database, triggering the v3 to v4 migration
        db = Database(str(db_dir))
        notes = db.conn.execute(
            "SELECT id, target_kind, conversation_id, text FROM notes "
            "WHERE conversation_id = 'c1'"
        ).fetchall()
        assert len(notes) == 1
        assert notes[0]["target_kind"] == "conversation"
        assert notes[0]["text"] == "an important thought"

        # Original enrichment note row should be gone
        remaining = db.conn.execute(
            "SELECT * FROM enrichments WHERE type = 'note'"
        ).fetchall()
        assert len(remaining) == 0

        # The note should be searchable via FTS5
        fts_rows = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'important'"
        ).fetchall()
        assert len(fts_rows) == 1
        assert "important" in fts_rows[0]["text"]

        # Schema version should be at current (v4+)
        from memex.db import SCHEMA_VERSION
        version_row = db.conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()
        assert version_row["version"] == SCHEMA_VERSION

        db.close()

    def test_v3_without_enrichment_notes_migrates_cleanly(self, tmp_path):
        """A v3 DB without any enrichment notes still migrates to v4 without errors."""
        db_dir = tmp_path / "testdb"
        db_dir.mkdir()
        db_path = str(db_dir / "conversations.db")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT, source TEXT, model TEXT, summary TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                starred_at DATETIME, pinned_at DATETIME, archived_at DATETIME,
                parent_conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
                sensitive BOOLEAN NOT NULL DEFAULT 0,
                metadata JSON NOT NULL DEFAULT '{}'
            );
            CREATE TABLE messages (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                id TEXT NOT NULL, role TEXT NOT NULL, parent_id TEXT, model TEXT,
                created_at DATETIME, sensitive BOOLEAN NOT NULL DEFAULT 0,
                content JSON NOT NULL, metadata JSON NOT NULL DEFAULT '{}',
                PRIMARY KEY (conversation_id, id)
            );
            CREATE TABLE tags (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                tag TEXT NOT NULL, PRIMARY KEY (conversation_id, tag)
            );
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                conversation_id UNINDEXED, message_id UNINDEXED, text,
                tokenize = 'porter unicode61'
            );
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            CREATE TABLE enrichments (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                type TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
                confidence REAL, created_at DATETIME NOT NULL,
                PRIMARY KEY (conversation_id, type, value)
            );
            CREATE TABLE provenance (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL, source_file TEXT, source_id TEXT,
                source_hash TEXT, imported_at DATETIME NOT NULL, importer_version TEXT,
                PRIMARY KEY (conversation_id, source_type)
            );
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (3)")
        conn.commit()
        conn.close()

        db = Database(str(db_dir))
        from memex.db import SCHEMA_VERSION
        version_row = db.conn.execute(
            "SELECT version FROM schema_version"
        ).fetchone()
        assert version_row["version"] == SCHEMA_VERSION
        # notes table exists and is empty
        count = db.conn.execute("SELECT count(*) AS n FROM notes").fetchone()
        assert count["n"] == 0
        db.close()


@pytest.fixture
def db_with_conversation(tmp_path):
    """A database with one conversation and one message, ready for note CRUD."""
    db = Database(str(tmp_path / "testdb"))
    db.conn.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) "
        "VALUES ('c1', 'Test', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    db.conn.execute(
        "INSERT INTO messages (conversation_id, id, role, content, created_at) "
        "VALUES ('c1', 'm1', 'user', '[]', '2026-01-01 00:00:00')"
    )
    db.conn.commit()
    yield db
    db.close()


class TestDatabaseNotesCRUD:
    def test_add_conversation_note(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(conversation_id="c1", text="conversation-level thought")
        assert note_id
        notes = db.get_notes(conversation_id="c1")
        assert len(notes) == 1
        assert notes[0]["text"] == "conversation-level thought"
        assert notes[0]["target_kind"] == "conversation"
        assert notes[0]["message_id"] is None
        assert notes[0]["conversation_id"] == "c1"

    def test_add_message_note(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(
            conversation_id="c1", message_id="m1", text="a key moment"
        )
        notes = db.get_notes(conversation_id="c1", message_id="m1")
        assert len(notes) == 1
        assert notes[0]["target_kind"] == "message"
        assert notes[0]["message_id"] == "m1"
        assert notes[0]["id"] == note_id

    def test_add_note_supplied_id(self, db_with_conversation):
        db = db_with_conversation
        supplied = "my-custom-note-id"
        returned = db.add_note(
            conversation_id="c1", text="supplied id", note_id=supplied
        )
        assert returned == supplied
        notes = db.get_notes(conversation_id="c1")
        assert notes[0]["id"] == supplied

    def test_add_note_populates_fts(self, db_with_conversation):
        db = db_with_conversation
        db.add_note(conversation_id="c1", text="searchable quokka reference")
        fts = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'quokka'"
        ).fetchall()
        assert len(fts) == 1
        assert "quokka" in fts[0]["text"]

    def test_update_note_changes_text(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(conversation_id="c1", text="original")
        db.update_note(note_id, "revised")
        notes = db.get_notes(conversation_id="c1")
        assert notes[0]["text"] == "revised"

    def test_update_note_reindexes_fts(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(conversation_id="c1", text="cat")
        db.update_note(note_id, "dog")
        cat_rows = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'cat'"
        ).fetchall()
        dog_rows = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'dog'"
        ).fetchall()
        assert cat_rows == []
        assert len(dog_rows) == 1

    def test_delete_note(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(conversation_id="c1", text="to be deleted")
        db.delete_note(note_id)
        assert db.get_notes(conversation_id="c1") == []

    def test_delete_note_removes_from_fts(self, db_with_conversation):
        db = db_with_conversation
        note_id = db.add_note(conversation_id="c1", text="ephemeral")
        db.delete_note(note_id)
        fts = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'ephemeral'"
        ).fetchall()
        assert fts == []

    def test_get_notes_by_target_kind(self, db_with_conversation):
        db = db_with_conversation
        db.add_note(conversation_id="c1", text="conv-level")
        db.add_note(conversation_id="c1", message_id="m1", text="msg-level")
        conv_notes = db.get_notes(conversation_id="c1", target_kind="conversation")
        msg_notes = db.get_notes(conversation_id="c1", target_kind="message")
        assert len(conv_notes) == 1
        assert len(msg_notes) == 1
        assert conv_notes[0]["text"] == "conv-level"
        assert msg_notes[0]["text"] == "msg-level"

    def test_search_notes_returns_matching(self, db_with_conversation):
        db = db_with_conversation
        db.add_note(conversation_id="c1", text="Kim was right about this")
        db.add_note(conversation_id="c1", text="completely unrelated thought")
        results = db.search_notes("Kim")
        assert len(results) == 1
        assert "Kim" in results[0]["text"]

    def test_search_notes_empty_query_returns_empty(self, db_with_conversation):
        db = db_with_conversation
        db.add_note(conversation_id="c1", text="whatever")
        results = db.search_notes("")
        assert results == []

    def test_search_notes_limit(self, db_with_conversation):
        db = db_with_conversation
        for i in range(10):
            db.add_note(conversation_id="c1", text=f"repeated keyword token {i}")
        results = db.search_notes("keyword", limit=3)
        assert len(results) == 3


class TestNotesOrphanSurvive:
    def test_orphaned_note_set_null_on_conversation_delete(self, db_with_conversation):
        db = db_with_conversation
        db.add_note(conversation_id="c1", text="survive me")
        db.conn.execute("DELETE FROM conversations WHERE id = 'c1'")
        db.conn.commit()
        rows = db.conn.execute(
            "SELECT id, conversation_id, text FROM notes"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["text"] == "survive me"
        assert rows[0]["conversation_id"] is None
