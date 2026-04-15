# CLAUDE.md

## Commands

```bash
# Run tests
pytest tests/memex/ -v

# Run with coverage
pytest tests/memex/ --cov=memex --cov-report=term-missing

# Install in development mode
pip install -e ".[dev]"

# Run a script
memex run --list
memex run redact --words "word1,word2" --level word
memex run redact --pattern-file api_keys.txt --level word --apply --yes
memex run enrich_trivial --apply
memex run note add --conv <id> "annotation text" --apply
memex run note list --conv <id>
memex run note search "query"
```

## Architecture

**Package structure:**
```
memex/
  __init__.py          # version (single source of truth; pyproject.toml reads it dynamically)
  __main__.py          # python -m memex
  models.py            # ContentBlock, Message, Conversation (tree)
  db.py                # Database (raw sqlite3, WAL, FTS5, migrations, schema v4)
  config.py            # YAML config, DatabaseRegistry (multi-database support)
  mcp.py               # FastMCP server (6 tools, 2 resources)
  assets.py            # Asset resolution, copying, media markdown rendering
  cli.py               # argparse CLI (import, export, show, db, mcp, run)
  scripts/
    __init__.py          # Discovery + runner utilities
    enrich_trivial.py    # Bulk-enrich trivial conversations
    redact.py            # Content redaction (word/message/conversation level)
    note.py              # Marginalia: add/list/search/delete notes
    patterns/            # Built-in regex pattern files
      api_keys.txt
      pii.txt
  importers/           # Convention-based: detect() + import_path()
    __init__.py          # Shared utilities: parse_timestamp(), detect_model()
    _claude_code_common.py  # Shared helpers for Claude Code importers
    openai.py
    anthropic.py
    gemini.py
    claude_code.py          # Claude Code JSONL sessions (conversation_only mode)
    claude_code_full.py     # Claude Code JSONL sessions (full fidelity: tool_use, thinking, tool_result)
  exporters/           # Convention-based: export()
    markdown.py          # Markdown export (includes notes as blockquotes)
    json_export.py       # JSON export (includes notes arrays)
    arkiv_export.py      # Arkiv universal record format (JSONL + schema.yaml via yaml.safe_dump)
    html.py              # HTML SPA exporter (outputs directory: index.html + DB + assets)
    html_template.py     # Self-contained HTML5 SPA template (composable functions)
```

**Key design decisions:**
- Raw sqlite3 (no ORM) -- WAL mode, FTS5, PRAGMA query_only for read-only
- Content blocks as plain dicts with "type" key -- not classes
- Conversation trees: Dict[str, Message] with parent_id links, _children index
- Convention-based plugins: modules with detect()/import_path() or export()
- Convention-based scripts: modules with `register_args()` + `run()` in `memex/scripts/` and `~/.memex/scripts/`
- FastMCP 2.x with lifespan pattern for DB lifecycle
- Cursor-based keyset pagination (base64-encoded updated_at + id)
- Schema versioning: `schema_version` table + `MIGRATIONS` dict for forward migrations (current: v4)
- Enrichments: structured metadata (summaries, topics, importance) with source tracking
- Notes (marginalia): polymorphic `target_kind` ('message' or 'conversation'), `ON DELETE SET NULL` for orphan survival
- Provenance: `_provenance` metadata convention in importers, persisted by CLI
- Media assets: `{db_dir}/assets/` stores copied media; URLs rewritten to `assets/{filename}` relative paths
- `Message.get_content_md()` renders text + media as markdown; `get_text()` stays text-only for FTS
- HTML SPA: composable string-returning functions, GitHub-primer style, light/dark mode via `data-theme` attribute + manual toggle, librarian agentic chat with tool use, notes UI with inline composer
- Auto-importer prefers `claude_code_full` over `claude_code` when both detect the same file
- Multi-database YAML config (`~/.memex/config.yaml`) with `sql_write: true` to enable writes via MCP
- pyproject.toml version is dynamic from `memex.__version__` (single source of truth)

## MCP Tools

| Tool | Purpose |
|---|---|
| `execute_sql` | Primary read interface for arbitrary SQL. Schema available via `memex://schema`. |
| `get_conversation` | Tree-aware retrieval + export (3 modes: metadata, messages, export) |
| `get_conversations` | Bulk retrieval with filters (ids, tag, source, model, search, starred, pinned) and optional full messages. Collapses the N+1 of execute_sql + get_conversation x N. |
| `update_conversations` | Modify conversation properties, tags, enrichments. Bulk 1..N. |
| `append_message` | Add message to conversation tree with consistency guarantees. |
| `add_note` | Annotate a message or conversation with a free-form text note (marginalia). |

**Resources:** `memex://schema` (DDL + relationships + FTS5 docs), `memex://databases` (multi-db discovery)

### Reading notes via execute_sql

Notes have their own table and FTS5 index. Read and search via `execute_sql`:

```sql
-- All notes for a conversation
SELECT id, target_kind, message_id, text, created_at FROM notes
WHERE conversation_id = ? ORDER BY created_at

-- FTS search across all notes
SELECT n.* FROM notes_fts f JOIN notes n ON n.id = f.note_id
WHERE notes_fts MATCH 'query'

-- Conversations with notes
SELECT DISTINCT c.id, c.title, COUNT(n.id) as note_count
FROM notes n JOIN conversations c ON c.id = n.conversation_id
GROUP BY c.id ORDER BY note_count DESC

-- Orphaned notes (survived re-import)
SELECT id, text, created_at FROM notes WHERE conversation_id IS NULL
```

When reading a conversation, also query notes for any annotations and include them in your understanding.

## Database

- Schema version: v4 (auto-migrates from v1/v2/v3 on first open)
- Composite PK on messages: (conversation_id, id)
- FTS5 virtual tables: `messages_fts` (porter unicode61), `notes_fts` (porter unicode61)
- FTS5 columns: `conversation_id` (UNINDEXED), `message_id` (UNINDEXED), `text`
- Tags in separate table with (conversation_id, tag) PK
- `parent_conversation_id` on conversations: self-referential FK, `ON DELETE SET NULL`
- Notes table: polymorphic `target_kind` ('message' or 'conversation'), FK with `ON DELETE SET NULL` (orphan survival)
- Enrichments table: PK (conversation_id, type, value), types: summary|topic|importance|excerpt (note type removed in v4, migrated to notes table)
- Provenance table: PK (conversation_id, source_type), tracks import origin
- PRAGMA query_only=ON when readonly=True (enforced at SQLite engine level)
- Database supports context manager: `with Database(path) as db:`
- Note CRUD: `add_note()`, `update_note()`, `delete_note()`, `get_notes()`, `search_notes()` -- all maintain notes_fts in sync
- `update_message_content()` updates content + re-indexes messages_fts
- `delete_conversation()` deletes with CASCADE + FTS5 cleanup
- `_escape_like()` for LIKE wildcard escaping; `_sanitize_fts_query()` for FTS5 query sanitization

## Testing

- Tests in `tests/memex/` -- 668 tests, 89%+ coverage
- `conftest.py` provides `tmp_db_path` fixture
- `test_notes.py` covers schema v4 migration, CRUD, FTS, orphan survival, MCP tool, CLI script, exporters
- Server tests exercise DB methods directly (MCP protocol testing deferred)
- `create_server(db=db)` sets PRAGMA query_only=ON; use `sql_write=True` for tests that call write tools directly
- `_get_tool_fn(server, name)` extracts the underlying function from FastMCP for direct invocation in tests

## HTML SPA Export

The HTML exporter produces a self-contained directory (index.html + conversations.db + assets/):

- **Template architecture**: `get_template(schema_ddl)` assembles from composable functions: `_css_variables()`, `_css_layout()`, `_css_components()`, `_html_structure()`, `_js_core()`, `_js_ui()`, `_js_notes()`, `_js_chat(schema_ddl)`, `_js_settings()`
- **Light/dark mode**: `data-theme` attribute on `<html>`, defaults to OS preference, manual sun/moon toggle saved to localStorage
- **Librarian chat**: agentic tool-use loop (streaming first round, non-streaming for tool rounds, max 5 rounds). System prompt includes schema DDL and notes tables. SQL guard rejects non-SELECT/EXPLAIN queries + `getRowsModified` runtime check.
- **Notes UI**: pencil icons on messages and headers, inline composer, edit/delete, persisted in sql.js in-memory DB. Graceful degradation for pre-v4 archives.
- **Security**: `escAttr()` for HTML attribute escaping, `safeMediaUrl()` allowlist for URLs (blocks javascript:/vbscript:), URL validation in renderMarkdown image/link regexes
- **Edge proxy**: default endpoint `metafunctor-edge.queelius.workers.dev/v1/messages` (no API key needed; proxy injects it server-side, locks model to haiku)

## Gotchas

- `Database(path, readonly=True)` sets PRAGMA query_only -- no writes possible
- `_auto_import` prefers `claude_code_full` over `claude_code` when both detect the same file
- `get_all_paths()` is iterative (not recursive) to handle 1000+ message chains
- FTS queries sanitize quotes via `_sanitize_fts_query()`; LIKE fallback uses `_escape_like()`
- `get_schema()` filters out FTS5 shadow tables and `schema_version` from output (for LLM consumption)
- `append_message` and `update_conversation` have try/except/rollback
- `save_conversation` uses INSERT OR REPLACE (triggers CASCADE delete on messages/tags/enrichments/provenance). Notes survive via `ON DELETE SET NULL`.
- Importers set `conv.metadata["_provenance"]` -- CLI pops it before save, writes to provenance table after (CASCADE-safe)
- Enrichment types validated in `update_conversations`: summary, topic, importance, excerpt (note type removed in v4)
- Enrichment sources validated in `update_conversations`: user, claude, heuristic
- Two Claude Code importers share `_claude_code_common.py`: `claude_code` (conversation_only, strips tool use/thinking) and `claude_code_full` (full fidelity). Both use `source="claude_code"`, differentiated by `importer_mode` metadata and provenance `source_type`
- `claude_code_full` imports subagent files from `subagents/` directories with `parent_conversation_id` links; subagent IDs are `{sessionId}:{agentId}` (deterministic); `conversation_only` skips subagents entirely
- Subagent records have `isSidechain=true` -- `_import_single(ignore_sidechain=True)` is used for subagent files
- `import_directory()` accepts `skip_subagents` param; subagents are imported per-parent-session, not via directory walk
- `--no-copy-assets` on import skips media asset resolution and copying
- `copy_assets` is idempotent: skips blocks already having `assets/` relative URLs
- HTML exporter outputs a directory (not a file): `index.html` + `conversations.db` + `assets/`
- `_cmd_export()` passes `db_path`, `db`, and `include_notes` to all exporters. `--no-notes` strips notes from output.
- HTML SPA search uses `LIKE '%term%'` on raw `messages.content` JSON (no FTS5 in sql.js)
- Enrichment type `original_content` used by redact script, not validated by MCP (DB layer has no type constraints)
- `update_message_content` must manually maintain messages_fts (no triggers)
- `delete_conversation` must clean messages_fts before DELETE (not CASCADE-covered)
- Note FTS (`notes_fts`) is maintained by `add_note`, `update_note`, `delete_note` -- not by triggers
- Redact script scans only `type="text"` content blocks; tool_use/thinking blocks in full-fidelity imports are not scanned (known limitation)
- MCP lifespan defaults config to `~/.memex/config.yaml` if `MEMEX_CONFIG` env var is unset; falls back to `~/.memex/default`
- `update_conversations` fails fast on readonly databases before entering the bulk loop
