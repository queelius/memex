# HTML Export Redesign

**Date:** 2026-03-14
**Status:** Design approved, pending implementation

## Context

The memex HTML export produces a self-contained SPA that loads a SQLite database via sql.js (Wasm) and lets users browse conversations in a browser. It is intended for public-facing deployment on metafunctor.com. The current version is dark-only with a terminal/monospace aesthetic. This redesign modernizes the visual design, adds light/dark mode, and introduces a "librarian" chat feature for querying across all conversations.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Visual style | Clean/GitHub-style | Sans-serif, pill badges, scannable. Professional for public site. |
| Theme mode | System preference (prefers-color-scheme) | No toggle needed. Pure CSS, zero JS overhead. |
| Top-level chat | Knowledgeable librarian | AI that queries the DB via tool use to answer questions about the archive. |
| Tool mechanism | Anthropic tool use (execute_sql) | Proper agentic pattern. API supports it natively. SPA executes SQL via sql.js. |
| Model | Haiku via edge proxy | Free-tier friendly. Compensate with strong system prompt. |
| Chat persistence | In-memory JS array | Resets on reload. No schema changes needed. |
| File architecture | Split template into composable functions | Keep single-file pattern but improve maintainability. |

## 1. Visual Redesign

### Typography
- Body: System font stack (-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif)
- Code/metadata: Monospace only where semantically appropriate (code blocks, IDs)
- Sizes: 14px body, 13px secondary, 12px metadata, 20px conversation title

### Layout
Three-panel grid retained (sidebar, main, timeline bar):
- Sidebar (300px): Search box, filter chips (rounded pills), conversation list with hover/active states
- Main: Conversation header (title, pill badges for source/model/tags, message count), message stream, input area
- Timeline bar: Bottom bar with sparkline canvas, unchanged functionally

### Messages
- User messages: Neutral background (--bg-surface), no border
- Assistant messages: Left accent border (3px, blue/accent color)
- Role labels: Small, muted, above message content
- Spacing: 12px gap between messages, 12px internal padding

### Filter chips
Rounded pill badges. Inactive: outlined. Active: filled with accent tint. Click to toggle.

### Settings overlay
Same gear icon in header. Clean form fields matching the new style.

## 2. Light/Dark Mode

Pure CSS via prefers-color-scheme media query. No JavaScript, no toggle, no localStorage.

Dark palette is the default in :root. Light palette overrides via @media (prefers-color-scheme: light).

Dark tokens:
- --bg: #0d1117
- --bg-surface: #161b22
- --bg-overlay: #1c2128
- --text: #c9d1d9
- --text-muted: #8b949e
- --text-accent: #58a6ff
- --text-strong: #f0f6fc
- --border: #30363d
- --badge-bg: rgba(56, 139, 253, 0.15)
- --badge-text: #58a6ff
- --msg-user-bg: #161b22
- --msg-assistant-border: #58a6ff

Light tokens:
- --bg: #ffffff
- --bg-surface: #f6f8fa
- --bg-overlay: #f0f0f0
- --text: #24292f
- --text-muted: #656d76
- --text-accent: #0969da
- --text-strong: #24292f
- --border: #d0d7de
- --badge-bg: #ddf4ff
- --badge-text: #0969da
- --msg-user-bg: #f6f8fa
- --msg-assistant-border: #0969da

All CSS rules reference variables. No duplication of selectors.

## 3. Top-Level Librarian Chat

### UX flow
When no conversation is selected (home state), the main panel shows:
1. A welcome message: "Ask me anything about your conversations."
2. A chat input area (same textarea + send button as conversation chat)

Messages appear in the main panel in a chat thread format.

### Schema injection

The `get_template()` function signature becomes `get_template(schema_ddl: str = "") -> str`. At export time, `html.py` calls `db.get_schema()` and passes the result. The `_js_librarian()` function receives the schema string and embeds it in the system prompt. This keeps the schema in sync with the actual database automatically.

### System prompt

Injected by the SPA at runtime. Full text:

```
You are a knowledgeable librarian for this person's conversation archive. You can search and analyze their conversations using SQL queries.

DATABASE SCHEMA:
{schema_ddl}

IMPORTANT: This database is loaded via sql.js (WebAssembly SQLite). FTS5 virtual tables (messages_fts) are NOT available. Do NOT use MATCH queries. For text search, use: SELECT ... FROM messages WHERE content LIKE '%term%'

QUERY GUIDELINES:
- Always query before guessing. Do not invent conversation titles or content.
- Use LIKE with % wildcards for text search on messages.content (JSON array of content blocks).
- Conversation titles are in conversations.title. Search there first for topic questions.
- Tags are in the tags table (conversation_id, tag). Join with conversations as needed.
- Cite conversation titles and dates in your answers.
- Keep answers concise. Show relevant excerpts when helpful.
- Limit result sets (LIMIT 20) to avoid overwhelming context.

EXAMPLE QUERIES:
- Find conversations by topic: SELECT id, title, source, message_count, created_at FROM conversations WHERE title LIKE '%topic%' ORDER BY created_at DESC LIMIT 20
- Search message content: SELECT c.title, m.role, m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.content LIKE '%keyword%' LIMIT 10
- Count by source: SELECT source, COUNT(*) as n FROM conversations GROUP BY source ORDER BY n DESC
- Recent activity: SELECT id, title, source, message_count, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 10
```

### Tool definition

```json
{
  "name": "execute_sql",
  "description": "Run a read-only SQL query against the conversation database. Returns results as a JSON array of objects. Use this to search conversations, count records, and find specific messages. Always use LIKE for text search (FTS5/MATCH is not available).",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "SQL SELECT query to execute"
      }
    },
    "required": ["query"]
  }
}
```

### Welcome state

When no conversation is selected, the main panel shows a welcome message with clickable starter prompts:
- "What topics have I discussed most?"
- "Find conversations about Python"
- "Which conversations have the most messages?"
- "Show my recent activity"

Clicking a prompt fills the input and submits it.

### Agentic loop (client-side JS)

1. User types question
2. Build messages array (system, history, user message)
3. POST to edge proxy with tools containing execute_sql definition
4. Stream response (first round only — subsequent tool rounds use non-streaming)
5. If response contains tool_use content block:
   - Accumulate tool_use JSON from SSE content_block_delta events
   - On content_block_stop, parse the complete tool input
   - Extract SQL query string
   - Execute via query() helper (read-only, NOT exec())
   - Wrap in try/catch — SQL errors returned as tool_result text for self-correction
   - Append assistant message (with tool_use) and user message (with tool_result) to history
   - POST again (non-streaming)
   - Repeat (max 5 rounds)
6. When response contains text content block, render in chat thread
7. Re-enable input

### Error handling
- Network errors: Display "Could not reach the server. Check your connection." in the chat thread as a system message.
- API errors (non-200): Display "API error {status}: {message}" in the chat thread.
- SQL errors: Returned as tool_result for self-correction (not shown to user directly).
- Input disabled during in-flight requests (same pattern as per-conversation chat).

### Safety
- Librarian uses query() (read-only helper), never exec() (write helper). Both use the same sql.js DB instance, but query() cannot modify data.
- Max 5 tool rounds to prevent runaway loops.
- After cap, final POST appends instruction: "Respond with your best answer based on what you have found so far."

### Chat state
- History stored in a JS array (librarianMessages)
- Not persisted to DB or localStorage
- Resets on page reload
- Separate from per-conversation chat (which continues to work as before)

## 4. Settings and Model

The edge proxy locks the model to haiku server-side, ignoring any model parameter from the client. This means:
- The model field in settings is removed. It was misleading since the proxy overrides it regardless.
- The endpoint field remains (defaults to the edge proxy, can be changed to direct API).
- The API key field remains (optional when using the proxy, required for direct API).
- The system prompt field remains (used by both librarian and per-conversation chat).
- Per-conversation resume chat also goes through the proxy and uses haiku. This is a change from the current default of sonnet, but keeps the architecture simple and free-tier friendly.

## 5. File Architecture


Split html_template.py into composable string-returning functions:

- get_template(schema_ddl=""): Assembles the complete HTML document from parts below
- _css_variables(): Light/dark token sets
- _css_layout(): Grid, sidebar, main, timeline
- _css_components(): Messages, badges, filters, settings, input
- _html_structure(): The DOM skeleton
- _js_core(): DB loading, query helpers, state management
- _js_ui(): Rendering, filters, conversation display
- _js_librarian(): Top-level chat system prompt, tool loop, streaming
- _js_settings(): Settings overlay, localStorage

Each function returns a string. get_template() concatenates them into the final HTML document. Still one file, still no external dependencies at build time. Ships as a single index.html on export.

## 6. Edge Proxy

No changes needed. The proxy already:
- Accepts the full Anthropic Messages API format (including tools and tool_choice)
- Passes through anthropic-beta headers
- Locks model to haiku
- Injects API key server-side
- Allows localhost origins for development

## Non-goals

- Per-conversation resume chat is preserved functionally (new visual styling applied)
- No database writes from the librarian (read-only queries only)
- No mobile-responsive layout (desktop-first, can add later)
- No export/download of librarian chat transcripts
