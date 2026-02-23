# HTML SPA Export — Design Document

**Date:** 2026-02-22
**Status:** Approved

## Summary

A single-page HTML application that embeds sql.js (SQLite via WebAssembly) to provide a fully client-side conversation browser, search engine, timeline, and chat resumption interface. Deployable as static files on a Hugo site.

## File Layout

```
static/memex/
├── index.html          # SPA — all HTML/CSS/JS inline (~50-80 KB)
├── conversations.db    # SQLite DB (served as static binary)
└── assets/             # Media files (images, audio, etc.)
```

## Architecture

**sql.js** (SQLite compiled to Wasm, ~1.3 MB from CDN) loads the `.db` file into memory. All queries run client-side. The existing FTS5 index works natively.

**DB loading cascade:**
1. URL param: `?db=path/to/conversations.db`
2. Same-directory convention: `./conversations.db`
3. File picker: drag-and-drop or `<input type="file">`

**Asset resolution:** Media blocks with `assets/` relative URLs resolve automatically since `assets/` sits alongside `index.html`.

## UI Layout

Three-panel, minimal/terminal-inspired:

- **Left sidebar:** FTS5 search, faceted filters (source, tags, date range), virtual-scrolled conversation list
- **Main panel:** Conversation reader with markdown rendering, inline media, code highlighting (Prism.js inline). "Resume this chat" button at bottom.
- **Bottom bar:** Timeline scrubber — horizontal axis showing conversation density over time, click/drag to filter by date range

**Visual style:** Dark background, monospace font, minimal chrome. Messages separated by horizontal rules, role as headings. No bubbles/avatars.

## Search & Filtering

FTS5 search runs directly via sql.js against `messages_fts`. Faceted filters (source, tags, starred, date range) compose with AND via SQL WHERE clauses. Message-level search with highlighted snippets.

Virtual scrolling for conversation list (~50 visible DOM nodes, recycled on scroll). Lazy message loading per conversation.

## Resume Chat (Anthropic API)

Settings in localStorage: API key, model (default `claude-sonnet-4-6`), optional system prompt.

Flow: Collect conversation history from current path, POST to `https://api.anthropic.com/v1/messages` with `anthropic-dangerous-direct-browser-access: true` header. Stream response via SSE, INSERT new messages into sql.js in-memory DB.

Download updated DB: `db.export()` → Uint8Array → Blob → download as `.db` file.

## Media & Full Fidelity

- Images: `<img>` tags for `assets/` URLs and `data:` URIs
- Audio/video: native `<audio>`/`<video>` elements
- PDF: `<a>` link
- Unresolved media: placeholder with original URL
- Code blocks: Prism.js syntax highlighting (inlined)

## CLI Integration

New exporter `memex/exporters/html.py`:

```bash
memex export site/ --format html --db ~/.memex/default
```

Produces `index.html` + copies `conversations.db` + copies `assets/`. For Hugo: output to `static/memex/`.

## Data Profile

- 2,394 conversations, 74,269 messages, ~101 MB content text
- Full DB: ~280 MB
- 538 media messages
- sql.js loads full DB into browser memory (feasible for modern machines)

## Dependencies (all inline or CDN)

- sql.js (~1.3 MB Wasm + ~80 KB JS)
- Prism.js (~15 KB for common language grammars)
- No framework — vanilla JS, CSS custom properties for theming
