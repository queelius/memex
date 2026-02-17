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
  db.py                # Database (raw sqlite3, WAL, FTS5)
  config.py            # YAML config, DatabaseRegistry
  server.py            # FastMCP server (7 tools, 3 resources)
  cli.py               # argparse CLI (import, export, serve)
  importers/           # Convention-based: detect() + import_file()
    openai.py
    anthropic.py
    gemini.py
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

## Database

- Composite PK on messages: (conversation_id, id)
- FTS5 virtual table (messages_fts) with porter unicode61 tokenizer
- Tags in separate table with (conversation_id, tag) PK
- PRAGMA query_only=ON when readonly=True (enforced at SQLite engine level)
- Database supports context manager: `with Database(path) as db:`

## Testing

- Tests in `tests/memex/` -- 203 tests, 81% coverage
- `conftest.py` provides `tmp_db_path` fixture
- Server tests exercise DB methods directly (MCP protocol testing deferred)

## Gotchas

- `Database(path, readonly=True)` sets PRAGMA query_only -- no writes possible
- `_auto_import` searches built-in importers first, user dir (~/.memex/importers/) second
- `get_all_paths()` is iterative (not recursive) to handle 1000+ message chains
- FTS queries sanitize quotes; LIKE fallback escapes % and _ wildcards
- `append_message` and `update_conversation` have try/except/rollback
- `save_conversation` uses INSERT OR REPLACE (triggers CASCADE delete on messages/tags)
