# Marginalia (Per-Message and Per-Conversation Notes)

**Date:** 2026-04-09
**Status:** Design approved, pending implementation
**Target release:** 0.11.0

## Context

memex is named after Vannevar Bush's 1945 proposal for a personal knowledge device. Bush's memex wasn't primarily a storage system. It was a *pathfinding* tool built around two primitives: associative **trails** through documents, and **annotations** on those documents. The current memex (through 0.10.x) has a strong archive layer (typed conversation storage, FTS5, multi-provider importers, a tree model, an agentic librarian), but is missing both primitives.

This spec is for the first of the two: annotations. The user needs to be able to attach free-form text notes to specific messages and to whole conversations, search across those notes, export archives with or without notes, and have the librarian surface notes in its answers when relevant. Notes are the atom that trails, syntheses, and collections will later compose from.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Note target granularity | Message and conversation, via polymorphic `target_kind` column | Scale-free from day one. Collections and trails slot in later as new target_kinds without schema changes. |
| Table design | Single `notes` table with `target_kind` enum, composite with `conversation_id` + nullable `message_id` | One write path, one read path, one FTS table. Clean DB integrity via FK. |
| Multi-note per target | Yes, UUID `id` column | A message or conversation can accumulate notes over time. Each note is independently timestamped. |
| Editing | Editable (update text, bump `updated_at`), append-mostly | Users correct typos. Historical edit trails are deferred. |
| Re-import survival | Orphan-survive via `ON DELETE SET NULL` on `conversation_id` | Matches the existing subagent orphan pattern. User decides whether to clean up or repoint. |
| Existing `enrichments` note type | Migrated into `notes` table at schema v4 boundary, then removed from `VALID_ENRICHMENT_TYPES` | Single source of truth for notes. |
| Export default | Include notes by default, `--no-notes` to strip | The archive is already fully private. Notes are not a new privacy dimension. |
| Librarian context | Notes queryable via SQL in both surfaces, convention-driven pre-loading | Same code path, different instruction conventions per surface. Claude Code is instructed to pre-load, HTML SPA librarian queries on demand. |

## 1. Schema (v4)

New tables:

```sql
CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('message', 'conversation')),
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    message_id TEXT,
    text TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
CREATE INDEX idx_notes_target ON notes(conversation_id, message_id);
CREATE INDEX idx_notes_kind ON notes(target_kind);
CREATE VIRTUAL TABLE notes_fts USING fts5(
    note_id UNINDEXED,
    conversation_id UNINDEXED,
    message_id UNINDEXED,
    text,
    tokenize = 'porter unicode61'
);
```

Constraints enforced at application level (SQLite CHECK is not reliable for cross-column rules):
- `target_kind = 'message'` implies both `conversation_id` and `message_id` are non-null.
- `target_kind = 'conversation'` implies `conversation_id` is non-null and `message_id` is null.
- Orphaned notes (conversation_id NULL) may have `target_kind` of either kind. The application preserves the previous `message_id` if any for later re-pointing.

FTS5 maintenance follows the existing memex pattern: updates through application code, not triggers. See `update_message_content()` for the template.

`notes_fts` uses `note_id` (not `id`) as the unindexed column for consistency with `messages_fts.message_id`.

## 2. Schema Migration (v3 to v4)

Implemented as `MIGRATIONS[3]` in `memex/db.py`. Steps, in order, inside a single transaction:

1. `CREATE TABLE notes ...` (idempotent via `IF NOT EXISTS`).
2. `CREATE INDEX idx_notes_target ...`, `CREATE INDEX idx_notes_kind ...`.
3. `CREATE VIRTUAL TABLE notes_fts ...`.
4. Copy existing conversation-level notes from `enrichments`:
   ```sql
   SELECT conversation_id, value, created_at FROM enrichments WHERE type = 'note';
   ```
   For each row, insert into `notes` as `target_kind = 'conversation'` with a fresh UUID, and populate `notes_fts`.
5. `DELETE FROM enrichments WHERE type = 'note'`.
6. `UPDATE schema_version SET version = 4`.

The `VALID_ENRICHMENT_TYPES` set in `memex/mcp.py` drops `"note"` (code change, not migration).

## 3. Database Layer

Add to `memex/db.py`:

```python
def add_note(
    self,
    *,
    conversation_id: str,
    message_id: str | None = None,
    text: str,
    note_id: str | None = None,
) -> str:
    """Add a note to a message or conversation.

    If message_id is None, creates a conversation-level note.
    Returns the note id (caller-supplied or generated).
    """

def update_note(self, note_id: str, text: str) -> None:
    """Update an existing note's text and bump updated_at."""

def delete_note(self, note_id: str) -> None:
    """Delete a note and its FTS5 entry."""

def get_notes(
    self,
    *,
    conversation_id: str | None = None,
    message_id: str | None = None,
    target_kind: str | None = None,
) -> list[dict]:
    """Query notes by conversation, message, or target kind."""

def search_notes(self, query: str, limit: int = 50) -> list[dict]:
    """FTS5 search across note text. Returns list of note dicts."""
```

All methods maintain `notes_fts` in sync with `notes` (INSERT, UPDATE, DELETE).

## 4. MCP Layer

New tool in `memex/mcp.py`:

```python
@mcp.tool()
def add_note(
    conversation_id: str,
    text: str,
    message_id: str | None = None,
    db: str | None = None,
    ctx: Context = None,
) -> dict:
    """Add a free-form text note to a message or conversation.
    If message_id is provided, attaches to that specific message.
    Otherwise the note is a conversation-level annotation.
    Returns {"note_id": ..., "target_kind": ...}.
    """
```

Reads and searches use `execute_sql` against `notes` and `notes_fts`. The `memex://schema` resource output includes the `notes` and `notes_fts` DDL so the librarian can discover the tables.

`VALID_ENRICHMENT_TYPES` shrinks from `{summary, topic, importance, excerpt, note}` to `{summary, topic, importance, excerpt}`. Callers trying to add `note`-type enrichments get a validation error directing them to `add_note`.

No MCP tool for update or delete in 0.11.0. Users can edit via the HTML SPA or via direct SQL on a writable database. Edit/delete MCP tools are a 0.11.x follow-up.

## 5. CLI Layer

New built-in script: `memex/scripts/note.py`, following the existing convention (`register_args()` + `run(db, args, apply=True)`).

Subcommands (exposed via a positional `action` argument to keep the script convention simple):
- `memex run note add --conv <id> [--msg <id>] "note text" --apply` : add a note.
- `memex run note list --conv <id>` : list notes for a conversation.
- `memex run note search <query>` : FTS5 search.
- `memex run note delete <note_id> --apply` : delete a note.

Because the existing script convention doesn't natively do subcommands, this script parses a positional `action` argument and dispatches internally.

## 6. HTML SPA Integration

Changes in `memex/exporters/html_template.py`:

**CSS (in `_css_components`):**
- `.note` : container: left border `3px solid var(--text-muted)`, padding, italic
- `.note-meta` : small muted timestamp
- `.note-actions` : edit/delete buttons (inline, subtle)
- `.add-note-btn` : pencil icon that toggles the note composer
- `.note-composer` : textarea + save/cancel buttons

**HTML (in `_html_structure`):** the pencil icon is inserted dynamically by the JS layer on each rendered message and on the conversation header.

**JS (in `_js_ui` and a new `_js_notes`):**
- `loadNotesForConversation(convId)` : fetches all notes for a conversation via `query()` and caches in memory
- `renderNotesForMessage(msgId)` : finds the message div and appends note children
- `renderNotesForConversation()` : shows conversation-level notes in the header area
- `openNoteComposer(targetKind, convId, msgId)` : toggles composer UI
- `saveNote(targetKind, convId, msgId, text, noteId = null)` : writes a note via the sql.js write helper and maintains `notes_fts`
- `deleteNote(noteId)` : deletes via the sql.js write helper and maintains `notes_fts`

The HTML SPA writes to its in-memory sql.js copy of the DB. The user can download the modified DB via the existing `downloadDb()` function. This means the SPA is genuinely interactive for note-taking, not just a read-only view.

**Librarian system prompt update (in `_js_chat`):** add a paragraph describing the `notes` and `notes_fts` tables and instructing the librarian to query them when relevant to the user's question. Not pre-loaded into context.

## 7. Exporter Layer

All four exporters get note support:

**Markdown (`memex/exporters/markdown.py`):** Notes rendered as blockquotes under the annotated element. Conversation-level notes appear at the top of the conversation section. Message-level notes appear directly under the message.

**JSON (`memex/exporters/json_export.py`):** Each message gets an optional `notes` array field. Conversation dict gets an optional top-level `notes` array for conversation-level notes.

**Arkiv (`memex/exporters/arkiv_export.py`):** Each record's metadata gains an optional `notes` list (array of `{text, created_at}` objects).

**HTML (`memex/exporters/html.py`):** The DB is copied into the export directory with notes intact. The SPA template renders them on load.

**`--no-notes` flag:** Added to `_cmd_export` in `memex/cli.py`. When set, exporters receive an `include_notes=False` kwarg that suppresses all note output. Default is `include_notes=True`.

## 8. Tests

New `tests/memex/test_notes.py`:
- `TestSchemaV4Migration`: v3-to-v4 upgrade path, enrichment note migration, FTS index creation
- `TestDatabaseNotesCRUD`: add, update, delete, get for both target kinds, FTS maintenance
- `TestNotesOrphanSurvive`: re-import a conversation, verify notes survive with conversation_id=NULL and text preserved
- `TestNotesFTSSearch`: search returns correct results, query sanitization, empty-query handling
- `TestMCPAddNoteTool`: tool validation, target_kind routing, readonly database rejection
- `TestMCPSchemaMentionsNotes`: `memex://schema` resource includes notes table DDL
- `TestValidEnrichmentTypesExcludesNote`: attempting to add a `note`-type enrichment is rejected with a helpful error
- `TestCLINoteScript`: add, list, search, delete flows via subprocess
- `TestExporterNotes`: markdown, json, arkiv emit notes, `--no-notes` strips them, HTML SPA template references notes tables
- `TestHTMLSPANotesUI`: template contains expected CSS classes, JS functions, and add-note affordances

## 9. Non-goals for 0.11.0

- Span-level annotations (annotating characters 120-186 of a message). Whole-message only.
- Collection-level notes. Waits until collections exist as a first-class entity.
- Trail-level notes. Waits until trails exist.
- Edit history or version trail for notes. Append-mostly for now.
- MCP tools for update and delete. SQL via `execute_sql` suffices until the workflow needs more.
- Note tagging or typing beyond the `target_kind` dimension.
- Multi-user permissions. Single-user personal tool.

## 10. Non-functional requirements

- Schema v3 databases must upgrade cleanly to v4 on first open with a v4 codebase. Existing enrichment `note` rows must survive the migration.
- All existing 600 tests must continue to pass.
- No new runtime dependencies.
- The `notes` table is read-only when the database is opened with `readonly=True` (enforced by the existing `PRAGMA query_only` pattern).
- The HTML SPA must gracefully degrade on databases that don't have a `notes` table (for backward compatibility when users load a pre-0.11.0 archive into a new SPA).

## 11. Acceptance criteria

A release is acceptable when:

1. All 600+ existing tests pass, plus at least 20 new tests for the notes feature.
2. A fresh v3 database opens cleanly under the v4 codebase, with any existing enrichment notes migrated into the `notes` table.
3. A user can annotate a message via CLI, MCP, or the HTML SPA, and that annotation is visible across all three surfaces.
4. A user can export their archive to markdown, json, arkiv, or html and the notes are included by default.
5. A user can export with `--no-notes` and the output contains no trace of note content.
6. The librarian in the HTML SPA can answer "what notes have I written about X?" by querying `notes_fts`.
7. Re-importing a conversation leaves existing notes intact, marked as orphaned if their message is gone.
