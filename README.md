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

**Browse and search:**
```bash
memex show                               # list conversations
memex show <id>                          # view a conversation
```

**HTML export (self-contained SPA):**
```bash
memex export ./site --format html        # outputs index.html + DB + assets
```

**MCP server** (for Claude Desktop, etc.):
```bash
memex mcp
```

**Scripts:**
```bash
memex run --list                         # available scripts
memex run redact --words "secret" --level word --apply
memex run enrich_trivial --apply
```

## Supported Formats

| Format      | Import | Export |
|-------------|--------|--------|
| OpenAI      | Yes    | -      |
| Anthropic   | Yes    | -      |
| Gemini      | Yes    | -      |
| Claude Code | Yes    | -      |
| Markdown    | -      | Yes    |
| JSON        | -      | Yes    |
| HTML (SPA)  | -      | Yes    |

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
