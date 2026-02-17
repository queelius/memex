# Memex: Conversation Memory System

**Date**: 2026-02-16
**Status**: Design approved
**Predecessor**: CTK (conversation-tk) — to be archived

## Vision

Memex is a personal conversation knowledge base. It stores conversations as
trees, annotates them with rich metadata, connects them through semantic
similarity, and exposes everything through an MCP-first interface.

The name comes from Vannevar Bush's 1945 "As We May Think" — a personal device
for storing, annotating, and linking everything you've read and thought.

**What makes it different from a chat archive:**
- Conversations are trees, not flat logs. Branches preserve alternative paths.
- Multi-model continuation: pick up a GPT-4 conversation with Claude, and the
  tree records provenance.
- Summaries, annotations, and metadata live *alongside* conversations, not
  mixed into message content.
- Semantic search and similarity networks connect conversations by meaning.
- MCP-first: the primary interface is programmatic, not CLI.

## Package

- **PyPI name**: `memex`
- **Entry point**: `memex`
- **Python**: >=3.10
- **Key dependency**: FastMCP (not the low-level MCP SDK)

## Architecture: MCP-First

CTK was CLI-first with MCP bolted on. Memex inverts this: the MCP server is
the primary interface. A CLI exists for convenience but delegates to the same
core that the MCP server uses.

### Multi-Database Registry

Memex manages multiple named databases. Each database is an independent SQLite
file — its own schema, its own integrity. Federation is handled via SQLite's
`ATTACH DATABASE` for cross-DB queries.

```yaml
# ~/.memex/config.yaml
databases:
  personal:
    path: ~/memex/personal/
    description: "Personal OpenAI + Anthropic conversations"
  work:
    path: ~/memex/work/
    description: "Work conversations"
  research:
    path: ~/memex/research/
    description: "Research discussion archive"

primary: personal   # write operations default here
sql_write: false    # enable SQL writes (overridden by MEMEX_SQL_WRITE env var)
```

**Default behavior by operation type:**

| Operation | Default (no `db` param) | Rationale |
|-----------|------------------------|-----------|
| **Reads** (search, list, SQL) | All databases (federated) | Broadest view when looking for something |
| **Writes** (star, tag, append, set_title) | Primary database | Mutations need a definite target |

Tools accept an optional `db` parameter:
- Omit → default behavior (all for reads, primary for writes)
- `db: "personal"` → target that specific database
- `db: "all"` → explicit federation (for reads; rejected for writes)

Results from federated reads include a `db` field identifying the source
database for each result.

**Implementation**: SQLite `ATTACH DATABASE` mounts all registered DBs into a
single connection. Federated queries use `UNION ALL` across attached schemas.
SQLite supports up to 10 attached databases by default (125 with compile flag).

**MCP server configuration** (`.mcp.json`):

```json
{
  "mcpServers": {
    "memex": {
      "command": "python",
      "args": ["-m", "memex.mcp_server"],
      "env": {
        "MEMEX_CONFIG": "~/.memex/config.yaml",
        "MEMEX_SQL_WRITE": "false"
      }
    }
  }
}
```

For single-DB use (backwards compatible), `MEMEX_DATABASE_PATH` still works:

```json
{
  "env": { "MEMEX_DATABASE_PATH": "./dev/openai-db/" }
}
```

When `MEMEX_DATABASE_PATH` is set without a config file, memex operates in
single-DB mode with that database as both the default for reads and writes.

### Server Architecture

The MCP server is a single file (`server.py`, ~400 lines) using FastMCP
decorators. Database lifecycle managed via `lifespan`, accessed through
`Context` — no globals.

```python
# memex/server.py (sketch — 7 tools, 3 resources)
from contextlib import asynccontextmanager
from fastmcp import FastMCP, Context

@asynccontextmanager
async def lifespan(server):
    config = load_config()
    registry = DatabaseRegistry(config)
    server.state["registry"] = registry
    yield
    registry.close()

mcp = FastMCP("memex", lifespan=lifespan)

@mcp.tool(annotations={"readOnlyHint": True})
async def query_conversations(
    query: str = None, starred: bool = None, source: str = None,
    tag: str = None, limit: int = 20, cursor: str = None,
    db: str = None, ctx: Context
) -> dict:
    """Search + list conversations. FTS5 when query provided, filters always."""
    return ctx.fastmcp.state["registry"].get_db(db).query(query, ...)

@mcp.tool(annotations={"idempotentHint": True})
async def update_conversation(
    id: str, title: str = None, starred: bool = None, pinned: bool = None,
    add_tags: list[str] = None, db: str = None, ctx: Context
) -> dict:
    """Update any conversation property. Only provided fields change."""
    ...
```

Every tool: get registry from context, resolve `db`, call database method,
return structured data. FastMCP handles schema generation and transport.

### Three MCP Primitives

The MCP spec (2025-06-18) defines three primitive types. Memex uses all three.

#### Resources (passive context — the LLM reads these)

Resources provide data that can be loaded into LLM context without calling a
tool. They use URI templates for dynamic content.

| URI | Description |
|-----|-------------|
| `memex://schema` | Database schema — tables, columns, types, indexes. Enables LLM to write correct SQL. |
| `memex://databases` | List of registered databases with stats (counts, sources, models, tags). |
| `memex://conversations/{id}` | Conversation metadata + path listing (root-to-leaf paths with message counts and previews). Lightweight — no full message content. |

#### Tools (actions — the LLM calls these)

All tools carry MCP annotations (`readOnlyHint`, `destructiveHint`,
`idempotentHint`, `openWorldHint`) so clients can make trust decisions.
Tools return structured output with `outputSchema` where appropriate.

All tools accept an optional `db: str` parameter (omitted from tables below
for clarity). See Multi-Database Registry above for default behavior.

**7 tools total.** Consolidated from CTK's approach — fewer tools, same power.

Statistics available via `memex://databases` resource or SQL:
`SELECT source, COUNT(*) FROM conversations GROUP BY source`.

**SQL**

| Tool | Annotations | Description |
|------|-------------|-------------|
| `execute_sql` | readOnly* | Run SQL query. Read-only by default. `MEMEX_SQL_WRITE=true` env var or `sql_write: true` in config.yaml enables writes (env var takes precedence). When multiple DBs are registered, all are ATTACHed — users write `SELECT * FROM personal.conversations` for cross-DB queries. Returns structured rows + column metadata. |

*readOnly annotation set dynamically based on config.

**Discovery**

| Tool | Annotations | Description |
|------|-------------|-------------|
| `query_conversations` | readOnly | Combined search + list. Optional `query` param triggers FTS5 search; without it, returns chronological listing. Filters: starred, pinned, archived, sensitive, source, model, tag, before/after date. Cursor-paginated. |

Tags queryable via SQL: `SELECT tag, COUNT(*) FROM tags GROUP BY tag`.

**Tree Navigation**

| Tool | Annotations | Description |
|------|-------------|-------------|
| `list_paths` | readOnly | All root-to-leaf paths for a conversation. Returns path index, message count, first/last message preview, model attribution per segment. |
| `get_path_messages` | readOnly | Messages along a specific path. Params: `id`, `path_index` or `leaf_message_id`, `offset`, `limit`. Returns structured message objects with role, content, timestamp, model. |

**Update**

| Tool | Annotations | Description |
|------|-------------|-------------|
| `update_conversation` | idempotent | Update any conversation property. Params: `title`, `summary`, `starred` (bool), `pinned` (bool), `archived` (bool), `sensitive` (bool), `add_tags`, `remove_tags`, `metadata` (merge into existing). Only provided fields are changed. |

**Mutation**

| Tool | Annotations | Description |
|------|-------------|-------------|
| `append_message` | | Add a message to the conversation tree. `parent_message_id` determines position: leaf = extend path, non-leaf = create branch (fork). Provenance stored in columns: `model`, `created_at`. Extra context in message `metadata`: `{source, session_id}`. |
| `export_conversation` | readOnly | Export as markdown or JSON. Params: `id`, `format`, `path_index`. Returns content as string. |

#### Prompts (Phase 2)

Prompts are deferred to Phase 2. The Phase 1 building blocks (`get_path_messages`
+ `append_message` + `update_conversation`) already enable all workflows — the
LLM can continue conversations, analyze content, and store results without
scaffolding. Prompts make common workflows more reliable, not possible.

**Phase 2 prompt:** `continue_conversation(id, path_index)` — loads path as
alternating user/assistant messages with a system frame for continuation.
Scaffolds the "append back to tree" step that the LLM sometimes forgets.

**Not prompts** (the LLM does these naturally given the data):
- Analyze conversation — just return messages and ask in natural language
- Cross-reference — load multiple conversations, ask in natural language
- Summarize — same pattern; store result via `update_conversation` metadata

## Data Model

Designed from scratch. Not an evolution of CTK — a clean break.

### Design Principles

- **Columns for queryable fields** — anything you filter or sort on is a proper
  indexed column, not buried in JSON. Column access is O(log n) via B-tree;
  `json_extract()` is O(n × blob_size) per row.
- **JSON for extensible data** — `metadata` JSON column is purely user space.
  No reserved namespaces. System fields are columns.
- **Single source of truth** — no dual metadata (CTK's biggest anti-pattern was
  the same field in Python dataclass + SQLAlchemy column + JSON blob).
- **Composite keys** — messages use `(conversation_id, id)` primary key.
  No ID mangling (`conv_id::msg_id` is gone).
- **Content blocks** — message content is an ordered array of typed blocks.
  Preserves ordering, maps cleanly to all providers, extensible.

### SQL Schema

```sql
CREATE TABLE conversations (
    id             TEXT PRIMARY KEY,
    title          TEXT,
    source         TEXT,                        -- "openai", "anthropic", etc.
    model          TEXT,                        -- dominant model (convenience)
    summary        TEXT,
    message_count  INTEGER NOT NULL DEFAULT 0,  -- denormalized, maintained by trigger
    created_at     DATETIME NOT NULL,
    updated_at     DATETIME NOT NULL,
    starred_at     DATETIME,
    pinned_at      DATETIME,
    archived_at    DATETIME,
    sensitive      BOOLEAN NOT NULL DEFAULT 0,
    metadata       JSON NOT NULL DEFAULT '{}'   -- user-extensible, no reserved keys
);

CREATE TABLE messages (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    id              TEXT NOT NULL,
    role            TEXT NOT NULL,               -- "user", "assistant", "system", "tool"
    parent_id       TEXT,                        -- NULL for root messages
    model           TEXT,                        -- per-message provenance
    created_at      DATETIME,
    sensitive       BOOLEAN NOT NULL DEFAULT 0,
    content         JSON NOT NULL,              -- ordered array of content blocks
    metadata        JSON NOT NULL DEFAULT '{}', -- user-extensible
    PRIMARY KEY (conversation_id, id)
);

CREATE TABLE tags (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tag             TEXT NOT NULL,
    PRIMARY KEY (conversation_id, tag)
);

-- Full-text search (rebuilt on import, not incrementally maintained)
CREATE VIRTUAL TABLE messages_fts USING fts5(
    conversation_id UNINDEXED,
    message_id UNINDEXED,
    text,
    content='messages',
    content_rowid='rowid'
);

-- Embeddings for semantic similarity (Phase 2+)
CREATE TABLE embeddings (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    model           TEXT NOT NULL,              -- embedding model name
    vector          BLOB NOT NULL,              -- float32 array
    created_at      DATETIME NOT NULL,
    PRIMARY KEY (conversation_id, model)
);

CREATE TABLE similarities (
    conversation_id_a TEXT NOT NULL,
    conversation_id_b TEXT NOT NULL,
    model             TEXT NOT NULL,
    score             REAL NOT NULL,
    created_at        DATETIME NOT NULL,
    PRIMARY KEY (conversation_id_a, conversation_id_b, model)
);

-- Indexes
CREATE INDEX idx_conversations_source ON conversations(source);
CREATE INDEX idx_conversations_model ON conversations(model);
CREATE INDEX idx_conversations_created ON conversations(created_at);
CREATE INDEX idx_conversations_updated ON conversations(updated_at);
CREATE INDEX idx_conversations_starred ON conversations(starred_at) WHERE starred_at IS NOT NULL;
CREATE INDEX idx_conversations_pinned ON conversations(pinned_at) WHERE pinned_at IS NOT NULL;
CREATE INDEX idx_conversations_archived ON conversations(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX idx_messages_parent ON messages(conversation_id, parent_id);
CREATE INDEX idx_tags_tag ON tags(tag);
```

### Content Blocks

The `content` JSON column on messages stores an **ordered array of typed
content blocks**. This mirrors the format used by OpenAI and Anthropic APIs.

```json
// Simple text (95% of messages)
[{"type": "text", "text": "Hello world"}]

// Text with image (order preserved)
[
  {"type": "text", "text": "What's in this image?"},
  {"type": "media", "media_type": "image/png", "data": "base64..."}
]

// Tool use (assistant calling a tool)
[
  {"type": "text", "text": "I'll search for that."},
  {"type": "tool_use", "id": "call_123", "name": "search", "input": {"query": "test"}}
]

// Tool result (separate message, role="tool" or role="user")
[
  {"type": "tool_result", "tool_use_id": "call_123", "content": "Found 5 results"}
]

// Extended thinking + response
[
  {"type": "thinking", "text": "Let me reason through this..."},
  {"type": "text", "text": "The answer is 42."}
]
```

**Block types (5):**

| Type | Required | Optional | Maps From |
|------|----------|----------|-----------|
| `text` | `text` | — | All providers |
| `media` | `media_type` | `url`, `data`, `filename` | OpenAI `image_url`, Anthropic `image`/`document`, audio, video |
| `tool_use` | `id`, `name`, `input` | — | OpenAI `tool_calls`, Anthropic `tool_use` |
| `tool_result` | `tool_use_id` | `content`, `is_error` | OpenAI `tool` role, Anthropic `tool_result` |
| `thinking` | `text` | — | Anthropic extended thinking |

The MIME type on `media` discriminates subtypes: `image/png`, `audio/mp3`,
`application/pdf`, `video/mp4`. No need for separate block types — they all
share the same shape (`media_type` + `url` or `data`).

Design rules:
- **Always an array** — even for plain text. No string-vs-array polymorphism.
- **One media type** — MIME type discriminates. No `path` field (not portable).
- **Tool use ≠ tool result** — separate blocks on separate messages.
- **Extensible** — new types require no schema changes.

**Querying content blocks in SQL:**
```sql
-- Find messages with images
SELECT m.* FROM messages m, json_each(m.content) AS block
WHERE json_extract(block.value, '$.type') = 'media'
  AND json_extract(block.value, '$.media_type') LIKE 'image/%';

-- Extract text for FTS indexing
SELECT m.conversation_id, m.id,
       group_concat(json_extract(block.value, '$.text'), ' ') as full_text
FROM messages m, json_each(m.content) AS block
WHERE json_extract(block.value, '$.type') IN ('text', 'thinking')
GROUP BY m.conversation_id, m.id;

-- Cross-DB federated query
SELECT 'personal' as db, id, title FROM personal.conversations
UNION ALL
SELECT 'work' as db, id, title FROM work.conversations
WHERE title LIKE '%python%';
```

### Python Domain Model

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Content is stored as JSON — typed dicts, not rigid classes.
ContentBlock = Dict[str, Any]  # Always has "type" key

@dataclass
class Message:
    id: str
    role: str                                    # "user", "assistant", "system", "tool"
    content: List[ContentBlock]                  # ordered array of typed blocks
    parent_id: Optional[str] = None
    model: Optional[str] = None                  # per-message provenance
    created_at: Optional[datetime] = None
    sensitive: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_text(self) -> str:
        """Extract all text from content blocks."""
        return "\n".join(
            block["text"] for block in self.content
            if block["type"] == "text" and block.get("text")
        )

@dataclass
class Conversation:
    id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    source: Optional[str] = None
    model: Optional[str] = None
    summary: Optional[str] = None
    message_count: int = 0
    starred_at: Optional[datetime] = None
    pinned_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    sensitive: bool = False
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: Dict[str, Message] = field(default_factory=dict)
    root_ids: List[str] = field(default_factory=list)

    # Tree navigation methods: get_all_paths(), get_path(), get_children(), etc.
```

**Content block constructors** (convenience, not required):
```python
def text_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}

def media_block(media_type: str, *, url: str = None, data: str = None, filename: str = None) -> ContentBlock:
    block: ContentBlock = {"type": "media", "media_type": media_type}
    if url: block["url"] = url
    if data: block["data"] = data
    if filename: block["filename"] = filename
    return block

def tool_use_block(id: str, name: str, input: Dict[str, Any]) -> ContentBlock:
    return {"type": "tool_use", "id": id, "name": name, "input": input}

def tool_result_block(tool_use_id: str, content: Any = None, is_error: bool = False) -> ContentBlock:
    block: ContentBlock = {"type": "tool_result", "tool_use_id": tool_use_id}
    if content is not None: block["content"] = content
    if is_error: block["is_error"] = True
    return block

def thinking_block(text: str) -> ContentBlock:
    return {"type": "thinking", "text": text}
```

### Metadata Architecture

Summaries and annotations are metadata *about* the conversation, not messages
*in* the conversation. This separation is fundamental.

- `metadata` JSON on conversations: user-extensible. Path summaries, quality
  ratings, topic lists, any annotation.
- `metadata` JSON on messages: user-extensible. Per-message annotations.
- `sensitive` on both tables: proper BOOLEAN column. Conversations are
  sensitive at the whole-tree level. Messages can be individually marked.
  A path is sensitive if ANY message on it is marked sensitive.
- Sensitive conversations visible in local tools (search, list, SQL).
  Excluded from all exports by default; `--include-sensitive` to override.
- No encryption — the boundary is at the export step, not storage.

## Technology Choices

### FastMCP (not raw MCP SDK)

The current CTK MCP server uses the low-level `mcp.server.lowlevel.Server`
with manual JSON schema definitions. 890 lines, ~400 of which is boilerplate.

FastMCP provides:
- Decorator-based tool/resource/prompt registration
- Automatic schema generation from Python type annotations and dataclasses
- Tool annotations (readOnlyHint, etc.) as decorator params
- Structured output with outputSchema from return type annotations
- Resource templates with URI pattern matching
- Context parameter for logging and progress reporting

### Raw SQLite (no ORM)

No SQLAlchemy. Python's `sqlite3` stdlib module directly.

CTK's ORM caused problems: dual models (SQLAlchemy model + dataclass + JSON
blob, manually synced), `onupdate=func.now()` silently overwriting timestamps,
session management confusion. And we bypass the ORM anyway for FTS5,
`json_extract`, `json_each`, `ATTACH DATABASE`.

With 6 tables and a stable schema, an ORM adds complexity without value.
What you write is what runs. Migrations via a simple version table + SQL
scripts if ever needed.

```python
# memex/db.py — the entire database layer
import sqlite3

class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def save_conversation(self, conv: Conversation) -> None: ...
    def load_conversation(self, id: str) -> Conversation: ...
    def search(self, query: str, **filters) -> list[dict]: ...
    def execute_sql(self, sql: str, params=()) -> list[dict]: ...
```

SQLite's JSON functions (`json_extract`, `json_each`, `json_set`) enable
querying inside metadata JSON without schema changes. Combined with
`execute_sql`, this gives infinite metadata flexibility.

SQLite's `ATTACH DATABASE` enables federated queries across multiple
database files without copying data.

### Minimal Dependencies

```
# Required
fastmcp>=2.14.0      # MCP server framework
pyyaml               # config.yaml parsing

# That's it for core.
```

No SQLAlchemy, no click, no rich. Importers/exporters may have optional deps.

### Convention-Based Import/Export

No plugin system. No base classes, no registry, no auto-discovery machinery.
Just directories of Python scripts with a simple function contract.

**Importers** (`memex/importers/`):

```python
# memex/importers/openai.py

def detect(path: str) -> bool:
    """Return True if this file looks like an OpenAI export."""

def import_file(path: str) -> list[Conversation]:
    """Import conversations from an OpenAI export file."""
```

**Exporters** (`memex/exporters/`):

```python
# memex/exporters/markdown.py

def export(conversations: list[Conversation], path: str, **kwargs) -> None:
    """Export conversations to markdown files."""
```

The directory is the registry. The filename is the format name. Adding a new
format = adding a new file. Versioning = `openai.py`, `openai_v2.py`.

**Discovery order** (first match wins):

1. `~/.memex/importers/` / `~/.memex/exporters/` — user scripts
2. `memex/importers/` / `memex/exporters/` — built-in

User scripts override built-in by filename. Drop a `slack.py` with `detect()`
+ `import_file()` in `~/.memex/importers/` — no package changes, no config.

Auto-detection: scan user importers first, then built-in. First `detect()`
returning `True` wins. Explicit: `memex import --format openai_v2 file.json`.

```
~/.memex/importers/           memex/importers/ (built-in)
├── slack.py                  ├── openai.py
├── custom_llm.py             ├── openai_v2.py
└── openai.py (override)      ├── anthropic.py
                              ├── gemini.py
~/.memex/exporters/           ├── copilot.py
├── notion.py                 ├── jsonl.py
└── obsidian.py               └── claude_code.py

                              memex/exporters/ (built-in)
                              ├── markdown.py
                              ├── json.py
                              ├── html.py
                              ├── jsonl.py
                              ├── hugo.py
                              └── csv.py
```

### Package Structure

Flat. ~10 files. No `core/` subdirectory — when there are only 5 modules,
nesting is noise.

```
memex/
├── __init__.py
├── __main__.py           # python -m memex
├── models.py             # Conversation, Message, content block constructors
├── db.py                 # Database (raw sqlite3, ~200 lines)
├── config.py             # Multi-DB registry, YAML config
├── server.py             # FastMCP server (primary interface)
├── cli.py                # Thin CLI (delegates to same core as server)
├── importers/
│   ├── openai.py
│   ├── anthropic.py
│   ├── gemini.py
│   └── ...
└── exporters/
    ├── markdown.py
    ├── json.py
    └── ...
```

Compare to CTK: 40+ files across `core/`, `integrations/`, `interfaces/`,
7 CLI modules. Memex achieves more with less.

### Views = SQL

CTK has a YAML-based view system (`ViewStore`, `ViewEvaluator`, selection
types: ITEMS, QUERY, SQL, UNION, INTERSECT, SUBTRACT). With `execute_sql`
available, a "view" is just a saved SQL query.

Saved queries live in `~/.memex/views/*.sql`. Execute with
`memex query --view recent-python` or via the SQL tool directly.

No ViewStore, no ViewEvaluator, no selection types. SQL is the query language.

## Phased Delivery

### Phase 1: Foundation (this sprint)

Rewrite MCP server on FastMCP. All tools with annotations and structured
output. Resources for schema and conversation content. SQL tool. Tree
navigation. Tags. Append message. Export. Set summary and metadata.
Multi-DB registry with federated reads.

Port from CTK (adapted to new model and conventions):
- Import scripts (openai, anthropic, gemini — rewritten as simple modules)
- Export scripts (markdown, JSON)
- FTS5 full-text search (indexing text from content blocks)

### Phase 2: Intelligence

- Prompt: `continue_conversation` (scaffolds path loading + append-back workflow)
- `find_related`: Embedding-similarity search
- Dot-path metadata helper (auto-create parent objects in JSON — Phase 1
  covers simple merges + `json_set()` via SQL)
- Remaining export formats (Hugo, CSV)
- `get_statistics` tool if the `memex://databases` resource proves insufficient

### Phase 3: Live HTML Export

Single-file HTML export that embeds the SQLite database via sql.js (SQLite
compiled to WebAssembly). The exported `.html` file IS the app:

- **Self-contained**: HTML + JS + CSS + embedded SQLite database in one file
- **Full browsing**: search, filter, tree navigation, path viewing — all
  client-side, no server needed
- **SQL console**: execute arbitrary queries against the embedded database
- **Portable**: share a single file, open in any browser

Future extension (Phase 4+):
- **API bridge**: JavaScript `fetch()` calls directly to OpenAI-compatible
  endpoints (or Anthropic, etc.) from the browser. User provides API key.
  Continue conversations, generate summaries — no backend needed.
- **Full standalone**: browse + search + chat, all client-side in one file.

Technology: [sql.js](https://github.com/sql-js/sql.js/) — SQLite compiled
to WebAssembly via Emscripten. The database is embedded as a base64 blob
in the HTML file or loaded from an adjacent `.db` file.

### Phase 4: Knowledge Graph

- Semantic search (RAG over conversation content)
- Conversation clustering by topic
- Knowledge timeline (topic evolution over time)
- Cross-conversation knowledge extraction

### Phase 5: Active Memory

- Auto-context injection: when discussing topic X, surface related past
  conversations as resources automatically
- Distilled knowledge: extract key facts/decisions from conversations into
  a structured knowledge base
- Multi-session continuation with model provenance tracking
- API bridge for live HTML export (see Phase 3)

## What Carries Over from CTK

- Import logic (OpenAI, Anthropic, Gemini, etc. — adapted for new model and contract)
- Export logic (Markdown, HTML, JSON, JSONL, Hugo, CSV — same)
- FTS5 full-text search (rewritten for content blocks)
- Embeddings and similarity infrastructure
- Utility patterns (parse_timestamp, try_parse_json)

## What Gets Left Behind

- CTK's data model (ConversationTree, ConversationMetadata, ConversationSummary,
  MessageContent, MediaContent, ToolCall — all replaced by cleaner designs)
- SQLAlchemy ORM (replaced by raw sqlite3)
- Plugin system (ImporterPlugin, ExporterPlugin, BasePlugin, PluginManager,
  auto-discovery — replaced by convention-based script directories)
- View system (ViewStore, ViewEvaluator — replaced by saved SQL files)
- Dual metadata anti-pattern (same field in dataclass + column + JSON)
- Message ID mangling (`conv_id::msg_id`)
- PathModel table (paths computed from tree structure)
- Network analysis tables (CurrentGraph, CurrentCommunity, CurrentNodeMetrics)
- CLI-first architecture (CLI becomes thin wrapper over core)
- TUI/shell mode (separate concern, may be reimplemented later)
- Legacy slash commands
- 890-line hand-rolled MCP server with manual JSON schemas
- The `helpers.py` lineage and module sprawl
- CLI module sprawl (cli.py, cli_conv.py, cli_db.py, cli_net.py, etc.)

## Decisions Made

1. **Name**: `memex` (available on PyPI)
2. **MCP framework**: FastMCP (not raw SDK)
3. **Multi-DB**: Named registry with federated reads, primary DB for writes
4. **SQL access**: Read-only by default, `MEMEX_SQL_WRITE=true` for writes
5. **Summary storage**: Metadata about the tree/path, not messages in the tree
6. **Repo strategy**: Continue in current repo, rename/restructure later
7. **Sensitivity**: Proper BOOLEAN columns on conversations + messages, export filter, no encryption
8. **No reserved namespace**: System fields are columns, metadata JSON is purely user space
9. **Provenance**: `model` + `created_at` columns on messages. Extra context (`source`, `session_id`) in metadata.
10. **SQL federation**: All DBs ATTACHed, raw SQL with qualified table names
11. **SQL write config**: `sql_write` in YAML config, `MEMEX_SQL_WRITE` env var takes precedence
12. **Data model**: Clean break from CTK. Single `Conversation` class (not Tree+Metadata+Summary)
13. **Composite PK**: Messages use `(conversation_id, id)` — no ID mangling
14. **Content blocks**: Ordered array of typed dicts. 5 block types. Always an array.
15. **No rigid content classes**: `ContentBlock = Dict[str, Any]` with constructor helpers
16. **Role is freeform TEXT**: Preserves provider-specific values ("user", "assistant", "system", "tool")
17. **Convention-based import/export**: Directory of scripts, no plugin system. Filename = format name. Versioning by filename.
18. **User-extensible scripts**: `~/.memex/importers/` and `~/.memex/exporters/` override built-in by filename.
19. **No SQLAlchemy**: Raw `sqlite3` stdlib.
20. **Flat package**: ~10 files, no `core/` nesting.
21. **Minimal deps**: `fastmcp` + `pyyaml`.
22. **Views = SQL**: Saved `.sql` files in `~/.memex/views/`.
23. **Live HTML export**: Self-contained HTML with embedded SQLite via sql.js (WebAssembly). Future: client-side chat via direct `fetch()` to LLM APIs.
24. **Consolidated tools**: 7 tools total. 9 organization tools → 1 `update_conversation`. 2 discovery tools → 1 `query_conversations`. Stats via resource + SQL. Tags via SQL.
25. **No slug column**: Display concern, not data. CLI uses ID prefix matching. Exports generate slugs on the fly.
26. **Dot-path metadata deferred**: Phase 1 uses simple merges + `json_set()` via SQL. Phase 2 adds auto-parent-creation helper.
27. **Unified media type**: 4 media block types (image/audio/video/document) → 1 `media` type. MIME type discriminates.
28. **Prompts deferred**: All prompts are Phase 2. Phase 1 tools enable all workflows; prompts make them reliable.
29. **No analyze/cross-reference prompts**: The LLM does these naturally given the data. Only `continue_conversation` gets scaffolding (Phase 2).
30. **Enriched conversation resource**: `memex://conversations/{id}` includes path listing. No separate path-level resources.
