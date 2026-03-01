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
memex mcp
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

When running as an MCP server, memex exposes 4 tools:

- `execute_sql` -- Primary read interface: all queries via SQL (read-only by default)
- `get_conversation` -- Tree-aware retrieval + export (metadata, messages, markdown/JSON)
- `update_conversations` -- Modify properties, tags, and enrichments (bulk)
- `append_message` -- Add messages to conversation trees

## Development

```bash
pytest tests/memex/ -v             # run tests
pytest tests/memex/ --cov=memex    # with coverage
```

## License

MIT
