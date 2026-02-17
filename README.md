# memex

Personal conversation knowledge base. MCP-first architecture for managing, searching, and analyzing chat conversations from multiple AI providers.

## Install

```bash
pip install -e ".[dev]"
```

## Quick Start

**Import conversations:**
```bash
memex import conversations.json          # auto-detects format
memex import export.json --format openai  # force format
```

**Export:**
```bash
memex export output.md --format markdown
memex export output.json --format json
```

**MCP server** (for Claude Desktop, etc.):
```bash
memex serve
```

## Supported Formats

| Provider  | Import | Export |
|-----------|--------|--------|
| OpenAI    | Yes    | -      |
| Anthropic | Yes    | -      |
| Gemini    | Yes    | -      |
| Markdown  | -      | Yes    |
| JSON      | -      | Yes    |

## MCP Tools

When running as an MCP server, memex exposes:

- `execute_sql` -- Run SQL queries (read-only by default)
- `query_conversations` -- FTS5 search with filters and pagination
- `list_paths` -- List conversation tree paths
- `get_path_messages` -- Read messages along a path
- `update_conversation` -- Star, pin, tag, annotate
- `append_message` -- Add messages to conversations
- `export_conversation` -- Export as markdown or JSON

## Development

```bash
pytest tests/memex/ -v             # run tests
pytest tests/memex/ --cov=memex    # with coverage
```

## License

MIT
