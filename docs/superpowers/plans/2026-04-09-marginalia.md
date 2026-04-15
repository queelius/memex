# Marginalia Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add per-message and per-conversation free-form text notes to memex, with CLI, MCP, HTML SPA, and exporter support. Ship as 0.11.0.

**Architecture:** Single `notes` table with polymorphic `target_kind`, managed via application-level FTS5 maintenance. Backward-compatible schema v4 migration that absorbs existing `note`-type enrichments. All four surfaces (CLI, MCP, HTML SPA, exporters) read and write through the same Database layer.

**Tech Stack:** Python 3.10+, raw sqlite3, FTS5, FastMCP 2.x, vanilla JavaScript (HTML SPA).

**Spec:** `docs/superpowers/specs/2026-04-09-marginalia-design.md`

---

## Chunk 1: Schema v4 + Database layer

### Task 1: Add schema v4 migration

**Files:**
- Modify: `memex/db.py`
- Test: `tests/memex/test_notes.py` (new)

- [ ] **Step 1: Write the failing test for schema v4 tables existing after upgrade**

Create `tests/memex/test_notes.py`:

```python
"""Tests for the notes feature (schema v4 marginalia)."""
import sqlite3
import pytest

from memex.db import Database, SCHEMA_VERSION


class TestSchemaV4:
    def test_schema_version_is_4(self):
        assert SCHEMA_VERSION == 4

    def test_fresh_database_has_notes_tables(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        tables = {r["name"] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "notes" in tables
        # FTS5 virtual tables create shadow tables
        assert "notes_fts" in tables
        db.close()

    def test_fresh_database_has_notes_indexes(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        indexes = {r["name"] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
        assert "idx_notes_target" in indexes
        assert "idx_notes_kind" in indexes
        db.close()
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/memex/test_notes.py::TestSchemaV4 -v --no-cov
```

Expected: `AssertionError: assert 'notes' in {...}` or `assert SCHEMA_VERSION == 4 (actual 3)`.

- [ ] **Step 3: Update SCHEMA_VERSION and add notes tables to SCHEMA_SQL**

In `memex/db.py`:

1. Change `SCHEMA_VERSION = 3` to `SCHEMA_VERSION = 4`.
2. Add to `SCHEMA_SQL`:

```sql
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('message', 'conversation')),
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT,
    text TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_target ON notes(conversation_id, message_id);
CREATE INDEX IF NOT EXISTS idx_notes_kind ON notes(target_kind);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    note_id UNINDEXED, conversation_id UNINDEXED, message_id UNINDEXED, text,
    tokenize = 'porter unicode61'
);
```

3. Add a migration entry:

```python
def _migrate_v3_to_v4(conn):
    """Add notes and notes_fts, migrate enrichment 'note' entries."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('message', 'conversation')),
            conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
            message_id TEXT,
            text TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_target ON notes(conversation_id, message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_kind ON notes(target_kind)")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            note_id UNINDEXED, conversation_id UNINDEXED, message_id UNINDEXED, text,
            tokenize = 'porter unicode61'
        )
    """)
    # Migrate existing conversation-level notes from enrichments
    import uuid
    rows = conn.execute(
        "SELECT conversation_id, value, created_at FROM enrichments WHERE type = 'note'"
    ).fetchall()
    for row in rows:
        note_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO notes (id, target_kind, conversation_id, message_id, text, created_at, updated_at) "
            "VALUES (?, 'conversation', ?, NULL, ?, ?, ?)",
            (note_id, row["conversation_id"], row["value"], row["created_at"], row["created_at"]),
        )
        conn.execute(
            "INSERT INTO notes_fts (note_id, conversation_id, message_id, text) VALUES (?, ?, NULL, ?)",
            (note_id, row["conversation_id"], row["value"]),
        )
    conn.execute("DELETE FROM enrichments WHERE type = 'note'")

MIGRATIONS = {
    1: _migrate_v1_to_v2,
    2: _migrate_v2_to_v3,
    3: _migrate_v3_to_v4,
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/memex/test_notes.py::TestSchemaV4 -v --no-cov
```

Expected: PASS.

- [ ] **Step 5: Verify existing tests still pass**

```bash
pytest tests/memex/ -q --tb=line --no-cov
```

Expected: 600 passed + new notes tests pass.

- [ ] **Step 6: Commit**

```bash
git add memex/db.py tests/memex/test_notes.py
git commit -m "feat(db): schema v4 adds notes and notes_fts tables"
```

---

### Task 2: Migrate existing enrichment notes at schema upgrade time

**Files:**
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write the failing test for enrichment note migration**

Add to `tests/memex/test_notes.py`:

```python
class TestSchemaV4EnrichmentMigration:
    def test_v3_enrichment_notes_move_to_notes_table(self, tmp_path):
        """A database with enrichment notes at v3 should have them in notes table after upgrade to v4."""
        db_dir = tmp_path / "testdb"
        db_dir.mkdir()
        db_path = str(db_dir / "conversations.db")

        # Create a v3 database manually with an enrichment note
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Apply v3 schema manually (subset needed for test)
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
            CREATE TABLE enrichments (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                type TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
                confidence REAL, created_at DATETIME NOT NULL,
                PRIMARY KEY (conversation_id, type, value)
            );
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (3);
            INSERT INTO conversations (id, title, created_at, updated_at)
                VALUES ('c1', 'test', '2025-01-01T00:00:00', '2025-01-01T00:00:00');
            INSERT INTO enrichments (conversation_id, type, value, source, created_at)
                VALUES ('c1', 'note', 'important thought', 'user', '2025-01-01T00:00:00');
        """)
        conn.commit()
        conn.close()

        # Open with current (v4) code, triggers migration
        db = Database(str(db_dir))
        notes = db.conn.execute(
            "SELECT id, target_kind, conversation_id, text FROM notes WHERE conversation_id = 'c1'"
        ).fetchall()
        assert len(notes) == 1
        assert notes[0]["target_kind"] == "conversation"
        assert notes[0]["text"] == "important thought"
        # Original enrichment should be deleted
        remaining = db.conn.execute(
            "SELECT * FROM enrichments WHERE type = 'note'"
        ).fetchall()
        assert len(remaining) == 0
        # Note should be in FTS
        fts_rows = db.conn.execute(
            "SELECT text FROM notes_fts WHERE notes_fts MATCH 'important'"
        ).fetchall()
        assert len(fts_rows) == 1
        db.close()
```

- [ ] **Step 2: Run test to verify pass (migration logic already in Task 1)**

```bash
pytest tests/memex/test_notes.py::TestSchemaV4EnrichmentMigration -v --no-cov
```

Expected: PASS (the migration logic was written in Task 1, this test just validates it).

- [ ] **Step 3: Commit**

```bash
git add tests/memex/test_notes.py
git commit -m "test(db): verify v3->v4 enrichment note migration"
```

---

### Task 3: Database CRUD methods for notes

**Files:**
- Modify: `memex/db.py`
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write failing tests for add_note, get_notes, update_note, delete_note**

Add to `tests/memex/test_notes.py`:

```python
class TestDatabaseNotesCRUD:
    def test_add_conversation_note(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        note_id = db.add_note(conversation_id="c1", text="conversation-level thought")
        assert note_id
        notes = db.get_notes(conversation_id="c1")
        assert len(notes) == 1
        assert notes[0]["text"] == "conversation-level thought"
        assert notes[0]["target_kind"] == "conversation"
        assert notes[0]["message_id"] is None
        db.close()

    def test_add_message_note(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.execute(
            "INSERT INTO messages (conversation_id, id, role, content, created_at) "
            "VALUES ('c1', 'm1', 'user', '[]', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        note_id = db.add_note(conversation_id="c1", message_id="m1", text="a key moment")
        notes = db.get_notes(conversation_id="c1", message_id="m1")
        assert len(notes) == 1
        assert notes[0]["target_kind"] == "message"
        assert notes[0]["message_id"] == "m1"
        db.close()

    def test_update_note(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        note_id = db.add_note(conversation_id="c1", text="original")
        db.update_note(note_id, "revised")
        notes = db.get_notes(conversation_id="c1")
        assert notes[0]["text"] == "revised"
        assert notes[0]["updated_at"] > notes[0]["created_at"]
        db.close()

    def test_delete_note(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        note_id = db.add_note(conversation_id="c1", text="to be deleted")
        db.delete_note(note_id)
        assert db.get_notes(conversation_id="c1") == []
        # FTS should also be clean
        fts = db.conn.execute(
            "SELECT * FROM notes_fts WHERE notes_fts MATCH 'deleted'"
        ).fetchall()
        assert fts == []
        db.close()

    def test_search_notes(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        db.add_note(conversation_id="c1", text="Kim was right about this")
        db.add_note(conversation_id="c1", text="completely unrelated thought")
        results = db.search_notes("Kim")
        assert len(results) == 1
        assert "Kim" in results[0]["text"]
        db.close()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/memex/test_notes.py::TestDatabaseNotesCRUD -v --no-cov
```

Expected: `AttributeError: 'Database' object has no attribute 'add_note'`.

- [ ] **Step 3: Implement the four CRUD methods in memex/db.py**

Add to `Database` class:

```python
def add_note(self, *, conversation_id, message_id=None, text, note_id=None):
    """Add a note to a message or conversation. Returns note id."""
    import uuid
    if note_id is None:
        note_id = str(uuid.uuid4())
    target_kind = "message" if message_id else "conversation"
    now = _fmt_dt(datetime.now())
    self.conn.execute(
        "INSERT INTO notes (id, target_kind, conversation_id, message_id, text, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (note_id, target_kind, conversation_id, message_id, text, now, now),
    )
    self.conn.execute(
        "INSERT INTO notes_fts (note_id, conversation_id, message_id, text) VALUES (?, ?, ?, ?)",
        (note_id, conversation_id, message_id, text),
    )
    self.conn.commit()
    return note_id

def update_note(self, note_id, text):
    """Update an existing note's text and bump updated_at."""
    now = _fmt_dt(datetime.now())
    self.conn.execute(
        "UPDATE notes SET text = ?, updated_at = ? WHERE id = ?",
        (text, now, note_id),
    )
    # Re-index FTS5: DELETE + INSERT (FTS5 doesn't support UPDATE of content)
    self.conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
    row = self.conn.execute(
        "SELECT conversation_id, message_id FROM notes WHERE id = ?", (note_id,)
    ).fetchone()
    if row:
        self.conn.execute(
            "INSERT INTO notes_fts (note_id, conversation_id, message_id, text) VALUES (?, ?, ?, ?)",
            (note_id, row["conversation_id"], row["message_id"], text),
        )
    self.conn.commit()

def delete_note(self, note_id):
    """Delete a note and its FTS5 entry."""
    self.conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
    self.conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    self.conn.commit()

def get_notes(self, *, conversation_id=None, message_id=None, target_kind=None):
    """Query notes by conversation, message, or target kind."""
    conds = []
    params = []
    if conversation_id is not None:
        conds.append("conversation_id = ?")
        params.append(conversation_id)
    if message_id is not None:
        conds.append("message_id = ?")
        params.append(message_id)
    if target_kind is not None:
        conds.append("target_kind = ?")
        params.append(target_kind)
    where = " AND ".join(conds) if conds else "1=1"
    rows = self.conn.execute(
        f"SELECT id, target_kind, conversation_id, message_id, text, created_at, updated_at "
        f"FROM notes WHERE {where} ORDER BY created_at ASC",
        tuple(params),
    ).fetchall()
    return [dict(r) for r in rows]

def search_notes(self, query, limit=50):
    """FTS5 search across note text."""
    from memex.db import _sanitize_fts_query
    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []
    fts_rows = self.conn.execute(
        "SELECT note_id FROM notes_fts WHERE notes_fts MATCH ? LIMIT ?",
        (sanitized, limit),
    ).fetchall()
    ids = [r["note_id"] for r in fts_rows]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = self.conn.execute(
        f"SELECT id, target_kind, conversation_id, message_id, text, created_at, updated_at "
        f"FROM notes WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/memex/test_notes.py::TestDatabaseNotesCRUD -v --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_notes.py
git commit -m "feat(db): add note CRUD methods with FTS5 maintenance"
```

---

### Task 4: Orphan-survive on conversation re-import

**Files:**
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write failing test for orphan survival**

Add:

```python
class TestNotesOrphanSurvive:
    def test_reimport_conversation_orphans_notes(self, tmp_path):
        db = Database(str(tmp_path / "testdb"))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Original', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        note_id = db.add_note(conversation_id="c1", text="survive me")

        # Simulate re-import: INSERT OR REPLACE on the conversation
        db.conn.execute(
            "INSERT OR REPLACE INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Reimported', '2026-01-01T00:00:00', '2026-01-02T00:00:00')"
        )
        db.conn.commit()

        # Notes should survive, either re-pointed at c1 (if FK is ON DELETE SET NULL
        # and REPLACE fires a cascade which sets NULL) or still pointing at c1.
        rows = db.conn.execute("SELECT id, conversation_id, text FROM notes").fetchall()
        assert len(rows) == 1
        assert rows[0]["text"] == "survive me"
        db.close()
```

- [ ] **Step 2: Run test to verify behavior**

```bash
pytest tests/memex/test_notes.py::TestNotesOrphanSurvive -v --no-cov
```

The test should PASS without additional code changes, because the schema already declares `ON DELETE SET NULL` on `notes.conversation_id`. Verify the behavior is as expected (note survives, possibly with `conversation_id = NULL`).

- [ ] **Step 3: Commit**

```bash
git add tests/memex/test_notes.py
git commit -m "test(db): verify notes orphan-survive conversation re-import"
```

---

## Chunk 2: MCP integration

### Task 5: add_note MCP tool

**Files:**
- Modify: `memex/mcp.py`
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write failing test for add_note tool**

Add to `tests/memex/test_notes.py`:

```python
class TestMCPAddNoteTool:
    def test_add_note_tool_creates_conversation_note(self, tmp_db_path):
        from memex.mcp import create_server, _get_tool_fn
        db = Database(tmp_db_path)
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        server = create_server(db=db, sql_write=True)
        add_note = _get_tool_fn(server, "add_note")
        result = add_note(conversation_id="c1", text="a thought")
        assert "note_id" in result
        assert result["target_kind"] == "conversation"
        notes = db.get_notes(conversation_id="c1")
        assert len(notes) == 1
        db.close()

    def test_add_note_tool_creates_message_note(self, tmp_db_path):
        from memex.mcp import create_server, _get_tool_fn
        db = Database(tmp_db_path)
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.execute(
            "INSERT INTO messages (conversation_id, id, role, content, created_at) "
            "VALUES ('c1', 'm1', 'user', '[]', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        server = create_server(db=db, sql_write=True)
        add_note = _get_tool_fn(server, "add_note")
        result = add_note(conversation_id="c1", message_id="m1", text="key moment")
        assert result["target_kind"] == "message"
        db.close()

    def test_add_note_tool_rejects_readonly(self, tmp_db_path):
        from memex.mcp import create_server, _get_tool_fn
        from fastmcp.exceptions import ToolError
        db = Database(tmp_db_path)
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        db.close()
        db = Database(tmp_db_path, readonly=True)
        server = create_server(db=db, sql_write=False)
        add_note = _get_tool_fn(server, "add_note")
        with pytest.raises(ToolError, match="writes are disabled"):
            add_note(conversation_id="c1", text="will fail")
        db.close()
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/memex/test_notes.py::TestMCPAddNoteTool -v --no-cov
```

Expected: tool not found.

- [ ] **Step 3: Implement add_note tool in memex/mcp.py**

Add within `_register_tools(mcp)`:

```python
@mcp.tool()
def add_note(
    conversation_id: Annotated[str, Field(description="Conversation ID the note attaches to")],
    text: Annotated[str, Field(description="Free-form text content of the note")],
    message_id: Annotated[str | None, Field(description="If set, attaches to this specific message (message-level note). If None, creates a conversation-level note.")] = None,
    db: Annotated[str | None, Field(description="Target database")] = None,
    ctx: Context = None,
) -> dict:
    """Add a free-form text note to a message or conversation.

    Use this when the user wants to annotate something in their archive with
    their own observations, thoughts, or corrections.
    """
    database = _get_db_from_ctx(mcp, ctx, db)
    if database.readonly:
        raise ToolError(
            "SQL writes are disabled for this database. "
            "Set MEMEX_SQL_WRITE=true to enable."
        )
    try:
        note_id = database.add_note(
            conversation_id=conversation_id,
            message_id=message_id,
            text=text,
        )
    except (ValueError, sqlite3.IntegrityError) as e:
        raise ToolError(str(e))
    return {
        "note_id": note_id,
        "target_kind": "message" if message_id else "conversation",
    }
```

- [ ] **Step 4: Update VALID_ENRICHMENT_TYPES to exclude 'note'**

```python
VALID_ENRICHMENT_TYPES = {"summary", "topic", "importance", "excerpt"}
```

And add a test:

```python
    def test_valid_enrichment_types_excludes_note(self, tmp_db_path):
        from memex.mcp import create_server, _get_tool_fn, VALID_ENRICHMENT_TYPES
        from fastmcp.exceptions import ToolError
        assert "note" not in VALID_ENRICHMENT_TYPES
        db = Database(tmp_db_path)
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        server = create_server(db=db, sql_write=True)
        update = _get_tool_fn(server, "update_conversations")
        with pytest.raises(ToolError, match="Invalid enrichment type"):
            update(
                ids=["c1"],
                add_enrichments=[{"type": "note", "value": "x", "source": "user"}],
            )
        db.close()
```

- [ ] **Step 5: Update schema resource to document notes tables**

The `memex://schema` resource is backed by `db.get_schema()` which returns the DDL of all non-internal tables. No code change needed since `notes` and `notes_fts` are real tables. Verify it shows up:

```python
    def test_schema_resource_mentions_notes(self, tmp_db_path):
        db = Database(tmp_db_path)
        schema = db.get_schema()
        assert "notes" in schema
        assert "notes_fts" in schema
        db.close()
```

- [ ] **Step 6: Run all MCP tests**

```bash
pytest tests/memex/test_mcp.py tests/memex/test_notes.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add memex/mcp.py tests/memex/test_notes.py
git commit -m "feat(mcp): add_note tool, drop note from enrichment types"
```

---

## Chunk 3: CLI script

### Task 6: memex run note script

**Files:**
- Create: `memex/scripts/note.py`
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write failing CLI tests**

```python
class TestCLINoteScript:
    def test_note_add_conversation(self, tmp_path):
        import subprocess
        import sys
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        db = Database(str(db_dir))
        db.conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('c1', 'Test', '2026-01-01T00:00:00', '2026-01-01T00:00:00')"
        )
        db.conn.commit()
        db.close()
        result = subprocess.run(
            [sys.executable, "-m", "memex", "run", "note", "--apply",
             "add", "--conv", "c1", "a cli thought"],
            capture_output=True, text=True,
            env={"MEMEX_DATABASE_PATH": str(db_dir), **os.environ},
        )
        assert result.returncode == 0, result.stderr
        db = Database(str(db_dir))
        notes = db.get_notes(conversation_id="c1")
        assert len(notes) == 1
        assert notes[0]["text"] == "a cli thought"
        db.close()

    def test_note_list_conversation(self, tmp_path):
        # similar setup, then list
        pass

    def test_note_search(self, tmp_path):
        # similar setup, then search
        pass

    def test_note_delete(self, tmp_path):
        # similar setup, add then delete
        pass
```

- [ ] **Step 2: Create memex/scripts/note.py**

```python
"""Manage notes: add, list, search, delete.

Usage:
    memex run note add --conv <id> [--msg <id>] "text" --apply
    memex run note list --conv <id>
    memex run note search <query>
    memex run note delete <note_id> --apply
"""


def register_args(parser):
    parser.add_argument("action", choices=["add", "list", "search", "delete"])
    parser.add_argument("rest", nargs="*", help="action-specific arguments")
    parser.add_argument("--conv", help="conversation id")
    parser.add_argument("--msg", help="message id (for message-level notes)")


def run(db, args, apply=True):
    action = args.action
    if action == "add":
        if not apply:
            print("note add requires --apply")
            return {"status": "dry_run"}
        if not args.conv:
            print("error: --conv required")
            return {"status": "error"}
        if not args.rest:
            print("error: note text required as positional argument")
            return {"status": "error"}
        text = " ".join(args.rest)
        note_id = db.add_note(
            conversation_id=args.conv, message_id=args.msg, text=text
        )
        print(f"Added note {note_id}")
        return {"status": "ok", "note_id": note_id}

    if action == "list":
        if not args.conv:
            print("error: --conv required")
            return {"status": "error"}
        notes = db.get_notes(conversation_id=args.conv)
        for n in notes:
            scope = f"msg {n['message_id']}" if n['message_id'] else "conversation"
            print(f"{n['id'][:8]}  [{scope}]  {n['text']}")
        return {"status": "ok", "count": len(notes)}

    if action == "search":
        if not args.rest:
            print("error: search query required")
            return {"status": "error"}
        query = " ".join(args.rest)
        results = db.search_notes(query)
        for n in results:
            scope = f"msg {n['message_id']}" if n['message_id'] else "conversation"
            print(f"{n['id'][:8]}  conv={n['conversation_id'][:8]}  [{scope}]  {n['text']}")
        return {"status": "ok", "count": len(results)}

    if action == "delete":
        if not apply:
            print("note delete requires --apply")
            return {"status": "dry_run"}
        if not args.rest:
            print("error: note id required")
            return {"status": "error"}
        note_id = args.rest[0]
        db.delete_note(note_id)
        print(f"Deleted note {note_id}")
        return {"status": "ok"}
```

- [ ] **Step 3: Run CLI tests**

```bash
pytest tests/memex/test_notes.py::TestCLINoteScript -v --no-cov
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add memex/scripts/note.py tests/memex/test_notes.py
git commit -m "feat(cli): add 'memex run note' script for CRUD on notes"
```

---

## Chunk 4: HTML SPA integration

### Task 7: Notes UI in HTML SPA

**Files:**
- Modify: `memex/exporters/html_template.py`
- Test: `tests/memex/test_html_export.py`

- [ ] **Step 1: Write failing tests for template contents**

```python
class TestHTMLNotesUI:
    def test_template_has_notes_css(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert ".note {" in html
        assert ".note-composer" in html
        assert ".add-note-btn" in html

    def test_template_has_notes_js(self):
        html = get_template()
        assert "function loadNotesForConversation" in html
        assert "function saveNote" in html
        assert "function deleteNote" in html

    def test_template_librarian_mentions_notes(self):
        html = get_template(schema_ddl="CREATE TABLE notes (id TEXT PRIMARY KEY); CREATE VIRTUAL TABLE notes_fts USING fts5(text);")
        # System prompt should instruct librarian to query notes
        assert "notes" in html.lower()
```

- [ ] **Step 2: Add CSS block to _css_components**

Add a notes CSS block with `.note`, `.note-composer`, `.note-meta`, `.note-actions`, `.add-note-btn` styles.

- [ ] **Step 3: Add JS functions to a new _js_notes module**

Implement `loadNotesForConversation`, `renderNotesForMessage`, `renderNotesForConversation`, `openNoteComposer`, `saveNote`, `deleteNote`. Integrate with `openConversation` so notes load when a conversation opens.

- [ ] **Step 4: Update _js_chat to mention notes tables in librarian system prompt**

Add a paragraph to `LIBRARIAN_SYSTEM_PROMPT` about the `notes` and `notes_fts` tables.

- [ ] **Step 5: Run tests**

```bash
pytest tests/memex/test_html_export.py tests/memex/test_notes.py -v --no-cov
```

- [ ] **Step 6: Manual visual verification**

Export and serve:

```bash
python -m memex export --format html --db ~/.memex/conversations /tmp/html-notes
cd /tmp/html-notes && python3 -m http.server 9880
```

Open http://localhost:9880, click a conversation, verify:
- Pencil icons appear on messages
- Clicking a pencil opens an inline composer
- Saving a note renders it under the message
- Notes persist if you refresh (through the in-memory DB, until download)
- Downloaded DB has the notes (`sqlite3 conversations.db "SELECT * FROM notes"`)

- [ ] **Step 7: Commit**

```bash
git add memex/exporters/html_template.py tests/memex/test_html_export.py tests/memex/test_notes.py
git commit -m "feat(html): notes UI with inline composer and sql.js persistence"
```

---

## Chunk 5: Exporter updates

### Task 8: Markdown, JSON, Arkiv exporters emit notes

**Files:**
- Modify: `memex/exporters/markdown.py`
- Modify: `memex/exporters/json_export.py`
- Modify: `memex/exporters/arkiv_export.py`
- Modify: `memex/cli.py` (`--no-notes` flag)
- Test: `tests/memex/test_notes.py`

- [ ] **Step 1: Write failing tests for each exporter**

```python
class TestExporterNotes:
    def test_markdown_export_includes_notes(self, tmp_path):
        # setup DB with a conversation + notes, export to markdown, assert notes in output
        pass

    def test_markdown_export_no_notes_flag(self, tmp_path):
        # same setup, export with include_notes=False, assert notes not in output
        pass

    def test_json_export_includes_notes(self, tmp_path):
        pass

    def test_arkiv_export_includes_notes(self, tmp_path):
        pass
```

- [ ] **Step 2: Update markdown exporter**

In `memex/exporters/markdown.py`, accept `include_notes=True` kwarg. Query notes via the passed-in db or a helper. Render conversation-level notes at top, message-level notes under their message.

- [ ] **Step 3: Update json exporter**

Accept `include_notes=True` kwarg. Add `notes` arrays to the output shape.

- [ ] **Step 4: Update arkiv exporter**

Accept `include_notes=True` kwarg. Include notes in metadata.

- [ ] **Step 5: Update CLI --no-notes flag**

Add `--no-notes` to the `export` subparser in `memex/cli.py`. Pass `include_notes=not args.no_notes` to the exporter's `export()` call.

- [ ] **Step 6: Run tests**

```bash
pytest tests/memex/test_notes.py tests/memex/test_exporters.py -v --no-cov
```

- [ ] **Step 7: Commit**

```bash
git add memex/exporters/ memex/cli.py tests/memex/test_notes.py
git commit -m "feat(exporters): include notes by default, --no-notes to strip"
```

---

## Chunk 6: Release 0.11.0

### Task 9: Docs + changelog + release

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `memex/__init__.py`

- [ ] **Step 1: Full test sweep**

```bash
pytest tests/memex/ -q --tb=line --no-cov
```

Expected: all passing.

- [ ] **Step 2: Bump version to 0.11.0**

Edit `memex/__init__.py`: `__version__ = "0.11.0"`.

- [ ] **Step 3: Update README**

Add a "Notes" section describing marginalia, CLI usage, HTML SPA affordance. Update MCP tool count from 5 to 6 (add_note).

- [ ] **Step 4: Update CLAUDE.md**

Document the new table, migration, MCP tool, CLI script. Update tool count.

- [ ] **Step 5: Commit, tag, push, build, publish**

```bash
git add memex/__init__.py README.md CLAUDE.md
git commit -m "release: memex 0.11.0 : marginalia (message and conversation notes)"
git push origin master
git tag v0.11.0
git push origin v0.11.0
rm -rf dist/ build/
python -m build
python -m twine upload dist/*
gh release create v0.11.0 --title "memex v0.11.0" --notes-file release-notes.md
```
