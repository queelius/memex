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
  mcp.py               # FastMCP server (4 tools, 2 resources)
  assets.py            # Asset resolution, copying, media markdown rendering
  cli.py               # argparse CLI (import, export, show, mcp, run)
  scripts/
    __init__.py          # Discovery + runner utilities
    enrich_trivial.py    # Bulk-enrich trivial conversations
    redact.py            # Content redaction (word/message/conversation level)
    patterns/            # Built-in regex pattern files
      api_keys.txt
      pii.txt
  importers/           # Convention-based: detect() + import_file()
    openai.py
    anthropic.py
    gemini.py
    claude_code.py     # Claude Code JSONL sessions (conversation_only mode)
  exporters/           # Convention-based: export()
    markdown.py
    json_export.py
    html.py            # HTML SPA exporter (outputs directory: index.html + DB + assets)
    html_template.py   # Self-contained HTML5 SPA template (sql.js Wasm, vanilla JS)
```

**Key design decisions:**
- Raw sqlite3 (no ORM) -- WAL mode, FTS5, PRAGMA query_only for read-only
- Content blocks as plain dicts with "type" key -- not classes
- Conversation trees: Dict[str, Message] with parent_id links, _children index
- Convention-based plugins: modules with detect()/import_file() or export()
- Convention-based scripts: modules with `register_args()` + `run()` in `memex/scripts/` and `~/.memex/scripts/`
- FastMCP 2.x with lifespan pattern for DB lifecycle
- Cursor-based keyset pagination (base64-encoded updated_at + id)
- Schema versioning: `schema_version` table + `MIGRATIONS` dict for forward migrations
- Enrichments: structured metadata (summaries, topics, importance) with source tracking
- Provenance: `_provenance` metadata convention in importers, persisted by CLI
- Media assets: `{db_dir}/assets/` stores copied media; URLs rewritten to `assets/{filename}` relative paths
- `Message.get_content_md()` renders text + media as markdown; `get_text()` stays text-only for FTS
- HTML SPA export: sql.js 1.14.0 (Wasm) loads DB client-side; no FTS5 (uses LIKE search); Anthropic API for chat resumption via `anthropic-dangerous-direct-browser-access` CORS header

## MCP Tools

| Tool | Purpose |
|---|---|
| `execute_sql` | Primary read interface — all queries via SQL. Schema available via `memex://schema`. |
| `get_conversation` | Tree-aware retrieval + export (3 modes: metadata, messages, export) |
| `update_conversations` | Modify conversation properties, tags, enrichments. Bulk 1..N. |
| `append_message` | Add message to conversation tree with consistency guarantees. |

**Resources:** `memex://schema` (DDL + relationships + FTS5 docs), `memex://databases` (multi-db discovery)

## Database

- Composite PK on messages: (conversation_id, id)
- FTS5 virtual table (messages_fts) with porter unicode61 tokenizer
- Tags in separate table with (conversation_id, tag) PK
- Enrichments table: PK (conversation_id, type, value), types: summary|topic|importance|excerpt|note
- Provenance table: PK (conversation_id, source_type), tracks import origin
- Schema versioning: `schema_version` table, `MIGRATIONS` dict, auto-applied on open
- PRAGMA query_only=ON when readonly=True (enforced at SQLite engine level)
- Database supports context manager: `with Database(path) as db:`
- `update_message_content()` — updates content + re-indexes FTS5
- `delete_conversation()` — deletes with CASCADE + FTS5 cleanup

## Testing

- Tests in `tests/memex/` -- ~484 tests, 84%+ coverage
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
- Enrichment types validated in `update_conversations`: summary, topic, importance, excerpt, note
- Enrichment sources validated in `update_conversations`: user, claude, heuristic
- Claude Code importer uses "conversation_only" mode (strips tool use, thinking, progress). Future `claude_code_full` importer can coexist for full-fidelity import
- `--no-copy-assets` on import skips media asset resolution and copying
- `copy_assets` is idempotent: skips blocks already having `assets/` relative URLs
- HTML exporter outputs a directory (not a file): `index.html` + `conversations.db` + `assets/`
- `_cmd_export()` passes `db_path=db.db_path` to all exporters; markdown/json accept `**kwargs`
- HTML SPA search uses `LIKE '%term%'` on raw `messages.content` JSON (no FTS5 in sql.js)
- Enrichment type `original_content` used by redact script, not validated by MCP (DB layer has no type constraints)
- `update_message_content` must manually maintain FTS5 (no triggers)
- `delete_conversation` must clean FTS5 before DELETE (not CASCADE-covered)
- Redact script uses `parse_known_args` remainder for script-specific args; `--apply`/`--db`/`--verbose` handled by framework
