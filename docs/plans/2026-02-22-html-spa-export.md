# HTML SPA Export — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a self-contained HTML5 SPA that loads a memex SQLite DB via sql.js (Wasm) and provides full conversation browsing, search, timeline, media rendering, and chat resumption via Anthropic API.

**Architecture:** Single `index.html` file (~80 KB) with all CSS/JS inline. sql.js v1.14.0 loaded from CDN. DB fetched as ArrayBuffer from same-directory, URL param, or file picker. Anthropic API called directly from browser with CORS header. New messages INSERT'd into in-memory DB, downloadable as `.db` file.

**Tech Stack:** Vanilla JS (no framework), CSS custom properties, sql.js 1.14.0 (Wasm), Anthropic Messages API (SSE streaming)

**Rollback point:** `ebfda09` (326 tests, 83% coverage)

**FTS5 note:** Standard sql.js does not include FTS5. Search uses `LIKE` on `messages.content` — fast enough for in-memory SQLite with <100K messages. The FTS5 virtual table in the DB is simply ignored.

---

## Task 1: Create the HTML skeleton + CSS + DB loading layer

**Files:**
- Create: `memex/exporters/html_template.py` — Python module containing the HTML template as a string constant
- Test: `tests/memex/test_html_export.py`

The SPA lives as a Python string in `html_template.py`, rendered by the exporter. This keeps the template maintainable and testable.

**Step 1: Write the HTML template module**

Create `memex/exporters/html_template.py` with a function `get_template() -> str` that returns the complete HTML document.

The HTML contains three sections: `<style>` (all CSS), the body markup, and `<script>` (all JS). The JS loads sql.js from CDN, fetches the DB, and boots the app.

**CSS design:** Terminal-inspired dark theme using CSS custom properties (--bg, --text, --border, --text-accent, etc.). Monospace font stack. Three-panel grid layout: sidebar (320px) | main (flex) over timeline bar (48px).

**DB loading cascade in JS:**
1. Check URL param `?db=path`
2. Try `fetch('./conversations.db')`
3. Fall back to file picker (drag-and-drop + input)

**JS helper `query(sql, params)`:** Wraps `db.prepare()` / `stmt.step()` / `stmt.getAsObject()` into a simple array-of-objects return. Also `exec(sql, params)` for writes using `db.run()`.

**Step 2: Write the initial test**

Create `tests/memex/test_html_export.py`:

```python
class TestHtmlTemplate:
    def test_template_is_valid_html(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert html.startswith('<!DOCTYPE html>')
        assert '</html>' in html
        assert 'sql-wasm.js' in html
        assert 'initApp' in html

    def test_template_contains_key_elements(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert 'id="search-box"' in html
        assert 'id="conv-list"' in html
        assert 'id="timeline-canvas"' in html
        assert 'id="settings-overlay"' in html
        assert 'anthropic-dangerous-direct-browser-access' in html
```

**Step 3: Run tests, commit**

```
pytest tests/memex/test_html_export.py -v
git add memex/exporters/html_template.py tests/memex/test_html_export.py
git commit -m "feat(memex): add HTML SPA template skeleton with DB loading layer"
```

---

## Task 2: Conversation list, search, and filters

**Files:**
- Modify: `memex/exporters/html_template.py` (add JS functions)

**Step 1: Add `onDbLoaded()`**

After DB loads: hide loading screen, show app grid, query distinct sources and tags for filter chips, call `initTimeline()`, call `loadConversations()`, wire up search input (debounced 200ms) and settings buttons.

**Step 2: Add `renderFilters()`**

Render source chips, tag chips (top 10), and a starred toggle as `<span class="filter-chip">` elements. Click toggles `activeFilters.source`/`activeFilters.tag`/`activeFilters.starred`, re-renders chips, and calls `loadConversations()`.

**Step 3: Add `loadConversations()`**

Build SQL dynamically:
- If search term: `SELECT DISTINCT c.* FROM conversations c JOIN messages m ON ... WHERE m.content LIKE ?` (LIKE search, no FTS5)
- Apply filters: source, tag (EXISTS subquery on tags table), starred (starred_at IS NOT NULL), date range
- `ORDER BY c.updated_at DESC LIMIT 500`

Render as `<div class="conv-item">` with title, meta (source, count, date). Click calls `openConversation(id)`.

**Step 4: Add `esc()` helper** — XSS-safe HTML escaping via `document.createElement('div').textContent = s; return div.innerHTML`.

**Step 5: Commit**

```
pytest tests/memex/test_html_export.py -v
git add memex/exporters/html_template.py
git commit -m "feat(memex): add conversation list, search, and filters to HTML SPA"
```

---

## Task 3: Conversation viewer with markdown + media rendering

**Files:**
- Modify: `memex/exporters/html_template.py` (add JS)

**Step 1: Add `openConversation(convId)`**

Query conversation metadata, messages (ORDER BY created_at), and tags. Call `renderConversation()`.

**Step 2: Add `renderConversation(conv, messages, tags)`**

Render header (title, source, model, tags, message count), then each message as `<div class="message">` with role heading and content. At the bottom, render resume chat area (textarea + send button).

**Step 3: Add `renderContent(blocks)`**

Iterate content blocks (parsed from JSON). Text blocks go through `renderMarkdown()`. Media blocks go through `renderMedia()`. Skip tool_use/tool_result/thinking.

**Step 4: Add `renderMedia(block)`**

- `image/*` with url or data URI: `<img>` tag with lazy loading
- `audio/*`: `<audio controls>`
- `video/*`: `<video controls>`
- Other: `<a>` link
- No src: `[filename]` placeholder

**Step 5: Add `renderMarkdown(text)`**

Lightweight hand-rolled markdown-to-HTML (~60 lines). Handles:
- Fenced code blocks (``` with language class)
- Inline code
- Headings (h1-h4)
- Bold, italic, bold+italic
- Images and links
- Horizontal rules
- Unordered lists
- Paragraph breaks

Important: escape HTML first (`&`, `<`, `>`), then apply markdown transforms. Code blocks must be escaped before other transforms run.

**Step 6: Add tests**

```python
class TestHtmlRendering:
    def test_template_has_render_functions(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert 'function renderContent(' in html
        assert 'function renderMedia(' in html
        assert 'function renderMarkdown(' in html
        assert 'function openConversation(' in html
```

**Step 7: Commit**

```
pytest tests/memex/test_html_export.py -v
git add memex/exporters/html_template.py tests/memex/test_html_export.py
git commit -m "feat(memex): add conversation viewer with markdown and media rendering"
```

---

## Task 4: Timeline scrubber

**Files:**
- Modify: `memex/exporters/html_template.py` (add JS)

**Step 1: Add `initTimeline()`**

Query monthly conversation counts: `SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count FROM conversations GROUP BY month ORDER BY month`.

Set timeline-start and timeline-end labels. Call `drawTimeline()`.

Wire up mouse events on canvas: mousedown starts drag, mousemove updates selection range, mouseup applies date filter and calls `loadConversations()`. Double-click clears selection.

Use ResizeObserver to redraw on resize.

**Step 2: Add `drawTimeline()`**

Canvas-based bar chart. Each month is a vertical bar, height proportional to count/maxCount. Selected range bars use accent color, others use border color. Handle devicePixelRatio for crisp rendering.

**Step 3: Commit**

```
pytest tests/memex/test_html_export.py -v
git add memex/exporters/html_template.py
git commit -m "feat(memex): add timeline scrubber to HTML SPA"
```

---

## Task 5: Settings, resume chat (Anthropic API), and DB download

**Files:**
- Modify: `memex/exporters/html_template.py` (add JS)

**Step 1: Add settings persistence**

`loadSettings()` reads from localStorage (memex_api_key, memex_model, memex_system_prompt), populates form fields. `saveSettings()` writes to localStorage. `openSettings()`/`closeSettings()` toggle the overlay.

**Step 2: Add `sendMessage()`**

Flow:
1. Check API key exists (open settings if not)
2. Build message history from DB: query all messages for current conversation, extract text from content blocks, build `[{role, content}]` array
3. Add user's new message to array
4. INSERT user message into DB (with crypto.randomUUID() for id, parent_id = last message)
5. Render user message in the conversation view
6. POST to `https://api.anthropic.com/v1/messages` with streaming enabled
7. Headers: Content-Type, x-api-key, anthropic-version: 2023-06-01, anthropic-dangerous-direct-browser-access: true
8. Read SSE stream: parse `data:` lines, extract `content_block_delta` events, accumulate text, render incrementally via renderMarkdown()
9. On completion: INSERT assistant message into DB, UPDATE conversation message_count and updated_at

**Step 3: Add `downloadDb()`**

`db.export()` returns Uint8Array. Create Blob, createObjectURL, trigger download as `conversations.db`.

**Step 4: Add tests**

```python
class TestHtmlAnthropicIntegration:
    def test_template_has_anthropic_api_code(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert 'api.anthropic.com/v1/messages' in html
        assert 'anthropic-dangerous-direct-browser-access' in html
        assert 'function sendMessage(' in html
        assert 'function downloadDb(' in html
        assert 'localStorage' in html
```

**Step 5: Commit**

```
pytest tests/memex/test_html_export.py -v
git add memex/exporters/html_template.py tests/memex/test_html_export.py
git commit -m "feat(memex): add settings, resume chat via Anthropic API, and DB download"
```

---

## Task 6: CLI exporter — `memex/exporters/html.py`

**Files:**
- Create: `memex/exporters/html.py`
- Modify: `memex/cli.py` (pass db_path to exporter)

**Step 1: Write the HTML exporter**

The HTML exporter outputs a **directory** (not a single file):
- `{path}/index.html` — the SPA (from `html_template.get_template()`)
- `{path}/conversations.db` — copy of the source DB file (via `shutil.copy2`)
- `{path}/assets/` — copy of media assets directory (via `shutil.copytree`)

Accepts `db_path` via `**kwargs`. If db_path not provided, only writes index.html.

**Step 2: Modify CLI to pass db_path**

In `_cmd_export()`, change the export call from:
```python
exporter_mod.export(convs, args.output)
```
to:
```python
exporter_mod.export(convs, args.output, db_path=db.db_path)
```

This is backwards-compatible — markdown and json exporters accept `**kwargs`.

**Step 3: Write tests**

```python
class TestHtmlExporter:
    def test_export_creates_directory(self, tmp_path):
        from memex.exporters.html import export
        out_dir = tmp_path / "site"
        export([conv], str(out_dir))
        assert (out_dir / "index.html").exists()

    def test_export_copies_db(self, tmp_path):
        # Create real DB, export, verify conversations.db copied
        ...

    def test_export_copies_assets(self, tmp_path):
        # Create source with assets/, export, verify assets/ copied
        ...

class TestCLIExportHtml:
    def test_cli_export_html(self, tmp_path):
        # Import OpenAI data, export as html, verify directory structure
        ...
```

**Step 4: Commit**

```
pytest tests/memex/test_html_export.py tests/memex/test_cli.py -v
git add memex/exporters/html.py memex/cli.py tests/memex/test_html_export.py
git commit -m "feat(memex): add HTML SPA exporter with CLI integration"
```

---

## Task 7: Update CLAUDE.md + final verification

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Add `html.py` and `html_template.py` to package structure. Add design decision note about sql.js Wasm approach.

**Step 2: Full test suite**

```
pytest tests/memex/ -v --tb=short
pytest tests/memex/ --cov=memex --cov-report=term-missing
```

Verify: all tests pass, coverage >= 80%.

**Step 3: Manual smoke test**

```
python -m memex export /tmp/memex-site --format html --db dev/openai_db
cd /tmp/memex-site && python -m http.server 8080
# Open http://localhost:8080 — verify: DB loads, search works, images visible, timeline works
```

**Step 4: Commit**

```
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for HTML SPA exporter"
```

---

## Verification Checklist

1. `pytest tests/memex/ -v` — all tests pass
2. `pytest tests/memex/ --cov=memex --cov-report=term-missing` — coverage >= 80%
3. `python -m memex export /tmp/test-site --format html --db dev/openai_db` — creates index.html + conversations.db + assets/
4. Open in browser — conversations load, search works, images render
5. Settings — API key saves to localStorage
6. Resume chat — streaming response from Anthropic API
7. Download DB — `.db` file downloads with new messages included
8. Timeline — drag to filter by date range, double-click to clear
9. File picker — works when no DB in same directory
