# HTML Export Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** Redesign the memex HTML export SPA with GitHub-style visual design, light/dark mode, and a top-level librarian chat that queries the conversation database via Anthropic tool use.

**Architecture:** The existing single-file html_template.py (1,627 lines) is split into composable string-returning functions while preserving the single-output-file guarantee. The html.py exporter gains schema injection. A new librarian chat feature implements an agentic tool-use loop entirely in client-side JavaScript, using sql.js for query execution and the edge proxy for AI responses.

**Tech Stack:** Python (template generation), vanilla JavaScript (SPA), sql.js 1.14.0 (Wasm SQLite), Anthropic Messages API with tool use, CSS custom properties with prefers-color-scheme.

**Spec:** docs/superpowers/specs/2026-03-14-html-export-redesign-design.md

---

## Chunk 1: File Architecture Refactor + Schema Injection

### Task 1: Split html_template.py into composable functions

This task restructures the existing template into smaller functions without changing any output. The generated HTML must be identical before and after.

**Files:**
- Modify: memex/exporters/html_template.py
- Modify: memex/exporters/html.py
- Test: tests/memex/test_integration.py (existing HTML export tests)

- [ ] **Step 1: Capture current output as reference**

Run the export and save the output for comparison:

```bash
python -m memex export --format html --db ~/.memex/conversations /tmp/html-ref
cp /tmp/html-ref/index.html /tmp/html-ref-snapshot.html
```

- [ ] **Step 2: Split get_template() into composable functions**

Replace the single get_template() function with:

```python
def get_template(schema_ddl: str = "") -> str:
    return _DOCTYPE + _css_all() + _html_body(schema_ddl)
```

Each helper function returns a string extracted from the current template:
- _css_variables(): Lines 25-48 (:root block)
- _css_layout(): Lines 50-97 (reset, scrollbar, #app grid)
- _css_components(): Lines 99-598 (sidebar, main, messages, timeline, settings, filters, drop-zone, etc.)
- _html_structure(): Lines 600-674 (the body DOM skeleton)
- _js_core(): Lines 678-847 (globals, query/exec helpers, DB loading cascade, state vars, esc/fmtDate helpers)
- _js_ui(): Lines 849-1413 (onDbLoaded, renderFilters, loadConversations, openConversation, renderConversation, renderContent, renderMedia, renderMarkdown, initTimeline, drawTimeline)
- _js_chat(schema_ddl): Lines 1415-1577 (sendMessage and resume-chat code)
- _js_settings(): Lines 1592-1627 (loadSettings, saveSettings, toggleSettings, boot)

Use raw string returns (triple-quoted) inside each function body.

- [ ] **Step 3: Verify output is identical**

```bash
python -m memex export --format html --db ~/.memex/conversations /tmp/html-check
diff /tmp/html-ref-snapshot.html /tmp/html-check/index.html
```

Expected: No diff (or only whitespace from the f-string join).

- [ ] **Step 4: Update html.py to pass schema_ddl**

Modify export() in html.py to extract the schema from the database and pass it to get_template(schema_ddl=schema_ddl). The db_path kwarg is already available. Open the DB directory with Database(readonly=True), call db.get_schema(), and pass the result.

- [ ] **Step 5: Run existing tests**

```bash
pytest tests/memex/test_integration.py -v -k html
```

Expected: All existing HTML export tests pass.

- [ ] **Step 6: Commit**

```bash
git add memex/exporters/html_template.py memex/exporters/html.py
git commit -m "refactor(html): split template into composable functions, add schema injection"
```

---

## Chunk 2: Visual Redesign + Light/Dark Mode

### Task 2: Replace CSS with GitHub-style design and light/dark tokens

**Files:**
- Modify: memex/exporters/html_template.py (_css_variables, _css_layout, _css_components)

- [ ] **Step 1: Replace _css_variables() with dual-theme tokens**

Dark tokens in :root, light tokens in @media (prefers-color-scheme: light) block. Use the exact values from the spec (section 2). Add new tokens: --font-sans, --font-mono, --badge-bg, --badge-text, --msg-user-bg, --msg-assistant-border, --input-bg.

- [ ] **Step 2: Replace _css_layout() with sans-serif grid**

Change font-family from monospace to the system sans-serif stack. Update --sidebar-width to 300px. Keep the grid structure (sidebar | main, timeline bar).

- [ ] **Step 3: Replace _css_components() with GitHub-style components**

Key changes:
- Search box: Rounded corners (6px), subtle border, clean focus ring
- Filter chips: border-radius 12px, outlined inactive, filled active with --badge-bg/--badge-text
- Conversation list items: More padding (10px 12px), title in 14px semibold, meta in 12px muted, active item with accent tint background
- Messages: User gets --msg-user-bg background with border-radius 8px. Assistant gets border-left 3px solid var(--msg-assistant-border). Role labels in 11px uppercase.
- Pill badges: In conversation header for source/model/tags. display inline-block, padding 2px 8px, border-radius 12px, font-size 11px, background var(--badge-bg), color var(--badge-text).
- Input area: Rounded textarea, clean send button
- Settings overlay: Match new style with rounded panel, clean form fields
- Scrollbars: Update to use new --border / --text-muted tokens

- [ ] **Step 4: Update _js_ui() rendering functions**

Modify renderConversation() to emit pill badges for source, model, and tags. Modify renderFilters() to use the new chip CSS classes. Ensure renderMarkdown() still works with sans-serif body text.

- [ ] **Step 5: Visual verification**

```bash
python -m memex export --format html --db ~/.memex/conversations /tmp/html-redesign
cd /tmp/html-redesign && python3 -m http.server 9877
```

Open http://localhost:9877 and verify:
- Light mode renders correctly (set OS to light)
- Dark mode renders correctly (set OS to dark)
- Conversation list is scannable
- Messages are readable with proper spacing
- Filter chips toggle correctly
- Settings overlay looks clean
- Timeline sparkline still renders (getComputedStyle picks up correct theme colors)

- [ ] **Step 6: Commit**

```bash
git add memex/exporters/html_template.py
git commit -m "feat(html): GitHub-style visual redesign with light/dark mode"
```

---

### Task 3: Remove model setting, simplify settings panel

**Files:**
- Modify: memex/exporters/html_template.py (_html_structure, _js_settings, _js_chat)

- [ ] **Step 1: Remove model field from settings HTML and JS**

In _html_structure(), remove the model settings-field div. In _js_settings(), remove memex_model from loadSettings() and saveSettings(). The request body can keep sending model (the proxy ignores it) so no change needed there.

- [ ] **Step 2: Run tests and verify**

```bash
pytest tests/memex/test_integration.py -v -k html
```

- [ ] **Step 3: Commit**

```bash
git add memex/exporters/html_template.py
git commit -m "fix(html): remove misleading model setting (proxy locks model)"
```

---

## Chunk 3: Librarian Chat Feature

### Task 4: Add welcome state with starter prompts

**Files:**
- Modify: memex/exporters/html_template.py (_css_components, _html_structure, _js_ui)

- [ ] **Step 1: Add welcome state CSS**

Add styles for .welcome (centered flex column), .starter-prompts (2-column grid), and .starter-prompt (clickable card with hover effect).

- [ ] **Step 2: Add welcome HTML to _html_structure()**

Add a welcome div inside the messages area with heading, subtitle, and 4 starter prompt divs. Each calls askLibrarian(this.textContent) on click.

- [ ] **Step 3: Wire up welcome/conversation state transitions in JS**

In _js_ui():
- onDbLoaded(): Show welcome state, show input area for librarian, set chatMode = "librarian"
- openConversation(): Hide welcome, show messages, set chatMode = "conversation"
- Add click handler on the header title "memex" to return to welcome state (reset librarian messages, clear messages area, show welcome)
- Add global: var chatMode = "librarian"

- [ ] **Step 4: Verify welcome state renders**

Export and open in browser. Verify welcome shows on load, conversations switch correctly, and clicking title returns to welcome.

- [ ] **Step 5: Commit**

```bash
git add memex/exporters/html_template.py
git commit -m "feat(html): add welcome state with starter prompts"
```

---

### Task 5: Implement librarian agentic chat loop

This is the core feature. The _js_chat() function gets rewritten to support both per-conversation resume chat and the new librarian mode with tool use.

**Files:**
- Modify: memex/exporters/html_template.py (_js_chat)

- [ ] **Step 1: Add constants and state**

_js_chat(schema_ddl) embeds:
- SCHEMA_DDL: The schema string escaped for JS
- LIBRARIAN_SYSTEM_PROMPT: Full system prompt from spec (section 3) with schema embedded
- EXECUTE_SQL_TOOL: Tool definition JSON from spec
- librarianMessages: Empty array for chat history
- MAX_TOOL_ROUNDS: 5

- [ ] **Step 2: Implement askLibrarian(text)**

Entry point for librarian mode. Adds user message to history and DOM. Creates assistant message div. Calls runAgenticLoop(). On completion, renders final text.

- [ ] **Step 3: Implement runAgenticLoop(assistContent, container)**

The agentic loop:
1. Build request body with system prompt, messages, tools
2. First round: streaming POST. Parse SSE for text or tool_use.
3. If tool_use: execute SQL via query() (read-only), append tool_result, POST again (non-streaming)
4. Repeat until text response or MAX_TOOL_ROUNDS
5. If max rounds hit: final POST without tools to force text response
6. Error handling: network errors and API errors shown as system messages

- [ ] **Step 4: Implement parseStreamResponse(response, assistContent, container)**

SSE parser that accumulates text deltas (renders progressively) and detects tool_use blocks (accumulates input_json_delta fragments, parses on content_block_stop). Returns {type: "text", text} or {type: "tool_use", toolUse}.

- [ ] **Step 5: Implement executeTool(toolUse)**

Calls query() (the read-only sql.js helper) with the SQL from toolUse.input.query. Wraps in try/catch. Truncates results to 50 rows. Returns JSON string.

- [ ] **Step 6: Implement helper functions**

- appendChatMessage(container, role, text): Creates and appends a message div, returns it. Uses esc() for role, renderMarkdown for text.
- appendSystemMessage(container, text): Creates error/system message div with danger color.

- [ ] **Step 7: Refactor sendMessage() to dispatch by mode**

sendMessage() checks chatMode:
- "librarian": calls askLibrarian(text)
- "conversation": calls resumeConversation(text)

Move the existing sendMessage() body into resumeConversation(text).

- [ ] **Step 8: Test the librarian chat end-to-end**

```bash
python -m memex export --format html --db ~/.memex/conversations /tmp/html-librarian
cd /tmp/html-librarian && python3 -m http.server 9878
```

Open http://localhost:9878. Verify:
1. Welcome state shows with 4 starter prompts
2. Clicking a prompt sends it to the librarian
3. The AI responds with SQL tool_use calls
4. The SPA executes the SQL and sends results back
5. The AI synthesizes a final text answer
6. Clicking a conversation switches to per-conversation mode
7. Per-conversation resume chat still works
8. Returning to welcome state resets the librarian

- [ ] **Step 9: Commit**

```bash
git add memex/exporters/html_template.py
git commit -m "feat(html): add librarian chat with agentic tool-use loop"
```

---

## Chunk 4: Polish and Verification

### Task 6: Final polish and test pass

**Files:**
- Modify: memex/exporters/html_template.py (minor fixes)
- Test: tests/memex/test_integration.py

- [ ] **Step 1: Fix the SyntaxWarning**

The current template has a SyntaxWarning from regex in the renderMarkdown function. Fix by ensuring the Python string properly escapes backslashes in the JS regex patterns. This likely requires doubling backslashes that are intended for JS regex.

- [ ] **Step 2: Add CSS for system messages**

Add .message.system styling with danger color and italic font-style.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/memex/ -v --tb=short
```

Expected: All 588+ tests pass.

- [ ] **Step 4: Full visual verification**

Export and test both themes:
- Dark mode: Verify all components render correctly
- Light mode: Switch OS theme and verify colors, contrast, readability
- Librarian: Ask 3-4 questions, verify tool use loop works
- Resume chat: Open a conversation, send a message, verify it works
- Timeline: Verify sparkline renders in both themes
- Filters: Verify chips toggle and filter correctly
- Search: Verify search works
- Settings: Verify gear icon opens overlay, endpoint/key/system-prompt save correctly

- [ ] **Step 5: Commit**

```bash
git add memex/exporters/html_template.py
git commit -m "fix(html): polish, fix SyntaxWarning, system message styling"
```

- [ ] **Step 6: Update CLAUDE.md with new HTML export architecture**

Add to the Architecture section under exporters the new composable function structure, light/dark mode mechanism, librarian chat agentic loop details, and edge proxy endpoint.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with HTML export architecture"
```
