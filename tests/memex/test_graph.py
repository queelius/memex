"""Tests for schema v5: edges, trails, marginalia v2.

Covers:
- v4 → v5 migration preserves existing notes, adds new columns with defaults
- Unversioned (pre-v1) → v5 migration works (the _create_missing_tables path)
- Edges: add/get/delete, uniqueness, direction filtering
- Trails: create, add steps, walk, reverse-index (trails containing a node)
- Notes v2: anchor fields, parent-child cascade, kind field
- prune_stale_edges sweeps dangling refs
"""
import sqlite3
from datetime import datetime

import pytest

from memex.db import Database, SCHEMA_VERSION
from memex.models import Conversation, Message, text_block


@pytest.fixture
def db(tmp_db_path):
    return Database(tmp_db_path)


@pytest.fixture
def seeded_db(db):
    """DB with one conversation and two messages, for target ids."""
    now = datetime.now()
    conv = Conversation(
        id="c1", created_at=now, updated_at=now, title="Test",
    )
    conv.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
    conv.add_message(Message(
        id="m2", role="assistant", content=[text_block("hello")], parent_id="m1",
    ))
    db.save_conversation(conv)
    return db


class TestSchemaV5:
    def test_schema_version(self):
        assert SCHEMA_VERSION == 5

    def test_fresh_db_has_v5_tables(self, db):
        tables = {
            r["name"]
            for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "edges" in tables
        assert "trails" in tables
        assert "trail_steps" in tables

    def test_fresh_db_has_notes_v2_columns(self, db):
        cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(notes)").fetchall()}
        for c in ("kind", "anchor_start", "anchor_end", "anchor_hash", "parent_note_id"):
            assert c in cols

    def test_edges_unique_constraint(self, db):
        idxs = [r["name"] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='edges'"
        ).fetchall()]
        assert "idx_edges_unique" in idxs


class TestV4ToV5Migration:
    def test_preserves_existing_notes(self, tmp_db_path, tmp_path):
        """An existing v4 DB should migrate to v5 without losing notes data."""
        import os
        # Build a v4 database shape manually.
        db_file = os.path.join(tmp_db_path, "conversations.db")
        raw = sqlite3.connect(db_file)
        raw.executescript(_V4_SCHEMA)
        raw.execute(
            "INSERT INTO conversations (id, created_at, updated_at) "
            "VALUES ('c1', '2024-01-01', '2024-01-01')"
        )
        raw.execute(
            "INSERT INTO notes (id, target_kind, conversation_id, message_id, "
            "text, created_at, updated_at) "
            "VALUES ('n1', 'conversation', 'c1', NULL, 'old note', "
            "'2024-01-01', '2024-01-01')"
        )
        raw.commit()
        raw.close()

        # Re-open via Database: migrations should run.
        db = Database(tmp_db_path)
        assert db.conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 5

        row = db.conn.execute(
            "SELECT id, text, kind, anchor_start, parent_note_id FROM notes WHERE id='n1'"
        ).fetchone()
        assert row["text"] == "old note"
        # New columns populated with their defaults
        assert row["kind"] == "freeform"
        assert row["anchor_start"] is None
        assert row["parent_note_id"] is None

    def test_migration_is_idempotent_on_preexisting_unversioned_db(self, tmp_path):
        """An un-versioned DB (no schema_version table) bootstraps cleanly."""
        import os
        db_dir = tmp_path / "bare"
        db_dir.mkdir()
        db_file = os.path.join(str(db_dir), "conversations.db")
        # Create a minimal conversations table with no schema_version, simulating
        # an old install. _create_missing_tables plus all migrations should run.
        raw = sqlite3.connect(db_file)
        raw.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT, source TEXT, model TEXT,
                summary TEXT, message_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                starred_at DATETIME, pinned_at DATETIME, archived_at DATETIME,
                sensitive BOOLEAN NOT NULL DEFAULT 0,
                metadata JSON NOT NULL DEFAULT '{}'
            );
        """)
        raw.commit()
        raw.close()
        # Opening the DB should drive it all the way to v5 without erroring.
        db = Database(str(db_dir))
        assert db.conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 5


class TestEdges:
    def test_add_and_retrieve(self, seeded_db):
        eid = seeded_db.add_edge(
            "message", "m1", "message", "m2", "answers",
            metadata={"confidence": 0.9},
        )
        edges = seeded_db.get_edges(node_kind="message", node_id="m1", direction="out")
        assert len(edges) == 1
        assert edges[0]["id"] == eid
        assert edges[0]["to_id"] == "m2"
        assert edges[0]["metadata"] == {"confidence": 0.9}

    def test_unique_constraint_same_type(self, seeded_db):
        """Same (from, to, edge_type) triple must not duplicate."""
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        with pytest.raises(sqlite3.IntegrityError):
            seeded_db.add_edge("message", "m1", "message", "m2", "answers")

    def test_different_edge_types_allowed(self, seeded_db):
        """Same nodes may have multiple edges of different types."""
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        seeded_db.add_edge("message", "m1", "message", "m2", "elaborates")
        edges = seeded_db.get_edges(node_id="m1", direction="out")
        types = {e["edge_type"] for e in edges}
        assert types == {"answers", "elaborates"}

    def test_direction_in_vs_out(self, seeded_db):
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        out = seeded_db.get_edges(node_id="m1", direction="out")
        in_ = seeded_db.get_edges(node_id="m2", direction="in")
        both = seeded_db.get_edges(node_id="m1", direction="both")
        assert len(out) == 1
        assert len(in_) == 1
        assert len(both) == 1

    def test_direction_both_returns_either_end(self, seeded_db):
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        seeded_db.add_edge("message", "m2", "message", "m1", "replies_to")
        both = seeded_db.get_edges(node_id="m1", direction="both")
        # Both the outgoing 'answers' and the incoming 'replies_to' should appear
        assert len(both) == 2

    def test_filter_by_edge_type(self, seeded_db):
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        seeded_db.add_edge("message", "m1", "message", "m2", "elaborates")
        answers_only = seeded_db.get_edges(node_id="m1", edge_type="answers")
        assert len(answers_only) == 1
        assert answers_only[0]["edge_type"] == "answers"

    def test_delete_edge(self, seeded_db):
        eid = seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        assert seeded_db.delete_edge(eid) is True
        assert seeded_db.get_edges(node_id="m1") == []

    def test_invalid_direction_raises(self, seeded_db):
        with pytest.raises(ValueError, match="direction"):
            seeded_db.get_edges(node_id="m1", direction="sideways")


class TestTrails:
    def test_create_and_walk(self, seeded_db):
        tid = seeded_db.create_trail("My Trail", "A reading path")
        seeded_db.add_trail_step(tid, "message", "m1", annotation="starts here")
        seeded_db.add_trail_step(tid, "message", "m2", annotation="follows")
        steps = seeded_db.walk_trail(tid)
        assert [s["position"] for s in steps] == [0, 1]
        assert steps[0]["target_id"] == "m1"
        assert steps[1]["annotation"] == "follows"

    def test_insert_at_position_shifts_later_steps(self, seeded_db):
        tid = seeded_db.create_trail("Reorderable")
        seeded_db.add_trail_step(tid, "message", "m1")  # position 0
        seeded_db.add_trail_step(tid, "message", "m2")  # position 1
        # Insert at position 0, should shift existing steps
        seeded_db.add_trail_step(tid, "conversation", "c1", position=0)
        steps = seeded_db.walk_trail(tid)
        assert steps[0]["target_id"] == "c1"
        assert steps[1]["target_id"] == "m1"
        assert steps[2]["target_id"] == "m2"

    def test_cascade_on_trail_delete(self, seeded_db):
        tid = seeded_db.create_trail("Doomed")
        seeded_db.add_trail_step(tid, "message", "m1")
        assert seeded_db.delete_trail(tid) is True
        # Steps should be gone via CASCADE
        row = seeded_db.conn.execute(
            "SELECT COUNT(*) as n FROM trail_steps WHERE trail_id = ?", (tid,),
        ).fetchone()
        assert row["n"] == 0

    def test_reverse_index_finds_trails_containing_node(self, seeded_db):
        t1 = seeded_db.create_trail("Trail A")
        t2 = seeded_db.create_trail("Trail B")
        seeded_db.add_trail_step(t1, "message", "m1")
        seeded_db.add_trail_step(t2, "message", "m1")
        seeded_db.add_trail_step(t2, "message", "m2")
        trails = seeded_db.trails_containing("message", "m1")
        ids = {t["id"] for t in trails}
        assert ids == {t1, t2}

    def test_list_includes_step_count(self, seeded_db):
        tid = seeded_db.create_trail("Listable")
        seeded_db.add_trail_step(tid, "message", "m1")
        seeded_db.add_trail_step(tid, "message", "m2")
        trails = seeded_db.list_trails()
        our = [t for t in trails if t["id"] == tid]
        assert len(our) == 1
        assert our[0]["step_count"] == 2


class TestMarginaliaV2:
    def test_anchor_fields_round_trip(self, seeded_db):
        nid = seeded_db.add_note(
            conversation_id="c1",
            message_id="m1",
            text="important point",
            kind="highlight",
            anchor_start=5,
            anchor_end=20,
            anchor_hash="sha256:abc",
        )
        row = seeded_db.conn.execute(
            "SELECT kind, anchor_start, anchor_end, anchor_hash FROM notes WHERE id = ?",
            (nid,),
        ).fetchone()
        assert row["kind"] == "highlight"
        assert row["anchor_start"] == 5
        assert row["anchor_end"] == 20
        assert row["anchor_hash"] == "sha256:abc"

    def test_kind_defaults_to_freeform(self, seeded_db):
        nid = seeded_db.add_note(
            conversation_id="c1", message_id="m1", text="just thinking",
        )
        row = seeded_db.conn.execute(
            "SELECT kind FROM notes WHERE id = ?", (nid,),
        ).fetchone()
        assert row["kind"] == "freeform"

    def test_parent_note_cascade(self, seeded_db):
        parent = seeded_db.add_note(
            conversation_id="c1", message_id="m1", text="parent note",
        )
        child = seeded_db.add_note(
            conversation_id="c1", message_id="m1", text="reply",
            parent_note_id=parent,
        )
        # Delete the parent — child should cascade
        seeded_db.delete_note(parent)
        row = seeded_db.conn.execute(
            "SELECT COUNT(*) as n FROM notes WHERE id = ?", (child,),
        ).fetchone()
        assert row["n"] == 0


class TestPruneStaleEdges:
    def test_prunes_edges_to_deleted_message(self, seeded_db):
        seeded_db.add_edge("message", "m1", "message", "m2", "answers")
        # Directly delete m2 (bypassing the typical delete_conversation path)
        seeded_db.conn.execute(
            "DELETE FROM messages WHERE conversation_id='c1' AND id='m2'"
        )
        seeded_db.conn.commit()
        # Edge still exists — nothing auto-prunes
        assert len(seeded_db.get_edges(node_id="m1")) == 1
        # Now explicitly sweep
        deleted = seeded_db.prune_stale_edges()
        assert deleted >= 1
        assert seeded_db.get_edges(node_id="m1") == []

    def test_leaves_unknown_kinds_alone(self, seeded_db):
        """Edges pointing to kinds outside memex (e.g. external_ref) must survive pruning."""
        seeded_db.add_edge("message", "m1", "external_ref", "urn:doi:10.xyz", "cites")
        seeded_db.prune_stale_edges()
        edges = seeded_db.get_edges(node_id="m1")
        assert len(edges) == 1
        assert edges[0]["to_kind"] == "external_ref"


# A v4-era schema replayed manually to seed the migration test above.
_V4_SCHEMA = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (4);
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
    tokenize='porter unicode61'
);
CREATE TABLE enrichments (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    type TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL, confidence REAL,
    created_at DATETIME NOT NULL, PRIMARY KEY (conversation_id, type, value)
);
CREATE TABLE provenance (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL, source_file TEXT, source_id TEXT, source_hash TEXT,
    imported_at DATETIME NOT NULL, importer_version TEXT,
    PRIMARY KEY (conversation_id, source_type)
);
CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('message', 'conversation')),
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT, text TEXT NOT NULL,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
);
CREATE VIRTUAL TABLE notes_fts USING fts5(
    note_id UNINDEXED, conversation_id UNINDEXED, message_id UNINDEXED, text,
    tokenize='porter unicode61'
);
CREATE INDEX idx_notes_target ON notes(conversation_id, message_id);
CREATE INDEX idx_notes_kind ON notes(target_kind);
"""
