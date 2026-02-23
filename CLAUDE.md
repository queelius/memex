# CLAUDE.md

## Commands

```bash
# Run tests
pytest tests/memex/ -v

# Run with coverage
pytest tests/memex/ --cov=memex --cov-report=term-missing

# Install in development mode
pip install -e ".[dev]"
```

## Architecture

**Package structure:**
```
memex/
  __init__.py          # version
  __main__.py          # python -m memex
  models.py            # ContentBlock, Message, Conversation (tree)
  db.py                # Database (raw sqlite3, WAL, FTS5, migrations)
  config.py            # YAML config, DatabaseRegistry
  mcp.py               # FastMCP server (8 tools, 2 resources)
  assets.py            # Asset resolution, copying, media markdown rendering
  cli.py               # argparse CLI (import, export, show, mcp)
  importers/           # Convention-based: detect() + import_file()
    openai.py
    anthropic.py
    gemini.py
    claude_code.py     # Claude Code JSONL sessions (conversation_only mode)
  exporters/           # Convention-based: export()
    markdown.py
    json_export.py
```

**Key design decisions:**
- Raw sqlite3 (no ORM) -- WAL mode, FTS5, PRAGMA query_only for read-only
- Content blocks as plain dicts with "type" key -- not classes
- Conversation trees: Dict[str, Message] with parent_id links, _children index
- Convention-based plugins: modules with detect()/import_file() or export()
- FastMCP 2.x with lifespan pattern for DB lifecycle
- Cursor-based keyset pagination (base64-encoded updated_at + id)
- Schema versioning: `schema_version` table + `MIGRATIONS` dict for forward migrations
- Enrichments: structured metadata (summaries, topics, importance) with source tracking
- Provenance: `_provenance` metadata convention in importers, persisted by CLI
- Media assets: `{db_dir}/assets/` stores copied media; URLs rewritten to `assets/{filename}` relative paths
- `Message.get_content_md()` renders text + media as markdown; `get_text()` stays text-only for FTS

## MCP Tools

| Tool | Purpose |
|---|---|
| `query_conversations` | Search/list conversations (FTS, title, filters, tags, enrichment filtering) |
| `get_conversation` | One tool for metadata, messages, or export (3 modes based on parameters) |
| `search_messages` | Message-level search with fts/phrase/like modes and context snippets |
| `update_conversations` | Bulk update 1..N conversations, returns updated state |
| `append_message` | Add message, returns created message + updated conversation metadata |
| `enrich_conversation` | Add enrichments (summary/topic/importance/excerpt/note) with validation |
| `query_enrichments` | Search enrichments by type, value, source, or conversation |
| `execute_sql` | Read-only SQL escape hatch (PRAGMA query_only enforced) |

**Resources:** `memex://schema` (DDL for execute_sql users), `memex://databases` (multi-db discovery)

## Database

- Composite PK on messages: (conversation_id, id)
- FTS5 virtual table (messages_fts) with porter unicode61 tokenizer
- Tags in separate table with (conversation_id, tag) PK
- Enrichments table: PK (conversation_id, type, value), types: summary|topic|importance|excerpt|note
- Provenance table: PK (conversation_id, source_type), tracks import origin
- Schema versioning: `schema_version` table, `MIGRATIONS` dict, auto-applied on open
- PRAGMA query_only=ON when readonly=True (enforced at SQLite engine level)
- Database supports context manager: `with Database(path) as db:`

## Testing

- Tests in `tests/memex/` -- ~326 tests, 83%+ coverage
- `conftest.py` provides `tmp_db_path` fixture
- Server tests exercise DB methods directly (MCP protocol testing deferred)

## Gotchas

- `Database(path, readonly=True)` sets PRAGMA query_only -- no writes possible
- `_auto_import` searches built-in importers first, user dir (~/.memex/importers/) second
- `get_all_paths()` is iterative (not recursive) to handle 1000+ message chains
- FTS queries sanitize quotes; LIKE fallback escapes % and _ wildcards
- `append_message` and `update_conversation` have try/except/rollback
- `save_conversation` uses INSERT OR REPLACE (triggers CASCADE delete on messages/tags/enrichments/provenance)
- Importers set `conv.metadata["_provenance"]` -- CLI pops it before save, writes to provenance table after (CASCADE-safe)
- Enrichment types validated at MCP layer: summary, topic, importance, excerpt, note
- Enrichment sources validated at MCP layer: user, claude, heuristic
- Claude Code importer uses "conversation_only" mode (strips tool use, thinking, progress). Future `claude_code_full` importer can coexist for full-fidelity import
- `--no-copy-assets` on import skips media asset resolution and copying
- `copy_assets` is idempotent: skips blocks already having `assets/` relative URLs
