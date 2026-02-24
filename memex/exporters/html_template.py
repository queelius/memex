"""HTML SPA template for self-contained memex conversation browser.

The template loads sql.js (Wasm) from CDN and can open a SQLite database
via URL parameter, fetch, or file picker. All CSS and JS are inlined
for single-file deployment.
"""


def get_template() -> str:
    """Return the complete HTML5 SPA document as a string.

    The document includes:
    - CSS: Terminal-inspired dark theme with CSS custom properties
    - Layout: Three-panel grid (sidebar | main, timeline bar)
    - JS: sql.js loading, DB cascade, query/exec helpers, placeholder functions
    """
    return '''\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>memex</title>
<style>
:root {
  --bg: #0d1117;
  --bg-surface: #161b22;
  --bg-overlay: #1c2128;
  --text: #c9d1d9;
  --text-muted: #8b949e;
  --text-accent: #58a6ff;
  --text-strong: #f0f6fc;
  --border: #30363d;
  --border-accent: #58a6ff;
  --success: #3fb950;
  --warning: #d29922;
  --danger: #f85149;
  --selection: rgba(88, 166, 255, 0.15);
  --sidebar-width: 320px;
  --timeline-height: 48px;
  --font-mono: "JetBrains Mono", "Fira Code", "SF Mono", "Cascadia Code",
    "Source Code Pro", ui-monospace, Menlo, Monaco, "Courier New", monospace;
  --font-size: 13px;
  --font-size-sm: 12px;
  --font-size-lg: 15px;
  --radius: 4px;
  --gap: 8px;
}

*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html, body {
  height: 100%;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--font-size);
  line-height: 1.5;
}

::selection {
  background: var(--selection);
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* Layout: three-panel grid */
#app {
  display: grid;
  grid-template-columns: var(--sidebar-width) 1fr;
  grid-template-rows: 1fr var(--timeline-height);
  height: 100vh;
  width: 100vw;
}

/* Sidebar */
#sidebar {
  grid-row: 1 / -1;
  grid-column: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  overflow: hidden;
}

#sidebar-header {
  padding: var(--gap);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

#search-box {
  width: 100%;
  padding: 6px 8px;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  outline: none;
  transition: border-color 0.15s;
}

#search-box:focus {
  border-color: var(--border-accent);
}

#search-box::placeholder {
  color: var(--text-muted);
}

#conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.conv-item {
  padding: 6px var(--gap);
  cursor: pointer;
  border-left: 2px solid transparent;
  transition: background 0.1s, border-color 0.1s;
}

.conv-item:hover {
  background: var(--bg-overlay);
}

.conv-item.active {
  background: var(--selection);
  border-left-color: var(--text-accent);
}

.conv-item-title {
  color: var(--text-strong);
  font-size: var(--font-size-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item-meta {
  color: var(--text-muted);
  font-size: 11px;
  margin-top: 2px;
}

#sidebar-footer {
  padding: var(--gap);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
  display: flex;
  gap: var(--gap);
  align-items: center;
}

#sidebar-footer .status {
  color: var(--text-muted);
  font-size: 11px;
}

/* Main content area */
#main {
  grid-row: 1;
  grid-column: 2;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

#main-header {
  padding: var(--gap) 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 40px;
}

#main-header h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

#messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.message {
  margin-bottom: 12px;
  padding: 8px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg-surface);
}

.message.user {
  border-left: 3px solid var(--text-accent);
}

.message.assistant {
  border-left: 3px solid var(--success);
}

.message-role {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 4px;
}

.message.user .message-role { color: var(--text-accent); }
.message.assistant .message-role { color: var(--success); }

.message-content {
  word-break: break-word;
}

/* Message input area */
#input-area {
  padding: var(--gap) 12px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
  display: flex;
  gap: var(--gap);
}

#message-input {
  flex: 1;
  padding: 6px 8px;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  outline: none;
  resize: none;
}

#message-input:focus {
  border-color: var(--border-accent);
}

/* Timeline bar */
#timeline {
  grid-row: 2;
  grid-column: 2;
  background: var(--bg-surface);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 12px;
  overflow: hidden;
}

#timeline-canvas {
  flex: 1;
  height: 32px;
  cursor: crosshair;
}

.timeline-label {
  color: var(--text-muted);
  font-size: 10px;
  white-space: nowrap;
  user-select: none;
  min-width: 0;
}

/* Settings overlay */
#settings-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 100;
  align-items: center;
  justify-content: center;
}

#settings-overlay.visible {
  display: flex;
}

#settings-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  width: 480px;
  max-width: 90vw;
  max-height: 80vh;
  overflow-y: auto;
}

#settings-panel h3 {
  color: var(--text-strong);
  margin-bottom: 12px;
}

/* File picker / drop zone */
#drop-zone {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  z-index: 200;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 16px;
}

#drop-zone.visible {
  display: flex;
}

#drop-zone-inner {
  border: 2px dashed var(--border-accent);
  border-radius: 8px;
  padding: 48px 64px;
  text-align: center;
  color: var(--text-accent);
  font-size: var(--font-size-lg);
}

#drop-zone-inner p {
  margin-bottom: 12px;
}

#file-input {
  display: none;
}

.btn {
  padding: 6px 12px;
  background: var(--bg-overlay);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s;
}

.btn:hover {
  background: var(--bg-surface);
  border-color: var(--text-muted);
}

.btn-primary {
  background: var(--text-accent);
  color: var(--bg);
  border-color: var(--text-accent);
}

.btn-primary:hover {
  opacity: 0.9;
}

/* Loading state */
#loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: var(--font-size-lg);
}

/* Filter chips */
#filters {
  padding: 4px var(--gap);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

#filters:empty {
  display: none;
  padding: 0;
  border: 0;
}

.filter-chip {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-muted);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.1s, border-color 0.1s, color 0.1s;
  white-space: nowrap;
  user-select: none;
}

.filter-chip:hover {
  border-color: var(--text-muted);
  color: var(--text);
}

.filter-chip.active {
  background: var(--text-accent);
  border-color: var(--text-accent);
  color: var(--bg);
}

/* Conversation header */
.conv-header {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.conv-header h2 {
  font-size: var(--font-size-lg);
  color: var(--text-strong);
  margin-bottom: 4px;
}

.conv-header-meta {
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  margin-bottom: 6px;
}

.conv-header-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.conv-tag {
  display: inline-block;
  padding: 1px 6px;
  font-size: 11px;
  color: var(--text-accent);
  background: var(--selection);
  border: 1px solid var(--border-accent);
  border-radius: 10px;
}

/* Message content rendering */
.message-content pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px;
  overflow-x: auto;
  margin: 8px 0;
  white-space: pre;
}

.message-content code {
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 2px;
  font-size: var(--font-size-sm);
}

.message-content pre code {
  background: none;
  padding: 0;
}

.message-content img {
  max-width: 100%;
  border-radius: var(--radius);
  margin: 4px 0;
}

.message-content audio,
.message-content video {
  max-width: 100%;
  margin: 4px 0;
}

.message-content h1,
.message-content h2,
.message-content h3,
.message-content h4 {
  color: var(--text-strong);
  margin: 12px 0 4px 0;
}

.message-content ul {
  padding-left: 20px;
  margin: 4px 0;
}

.message-content hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 8px 0;
}

.message-content a {
  color: var(--text-accent);
  text-decoration: none;
}

.message-content a:hover {
  text-decoration: underline;
}

.message-content p {
  margin: 4px 0;
}

/* System role messages */
.message.system {
  border-left: 3px solid var(--warning);
}

.message.system .message-role { color: var(--warning); }

/* Settings form */
.settings-field {
  margin-bottom: 12px;
}

.settings-field label {
  display: block;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  margin-bottom: 4px;
}

.settings-field input,
.settings-field textarea {
  width: 100%;
  padding: 6px 8px;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  outline: none;
}

.settings-field input:focus,
.settings-field textarea:focus {
  border-color: var(--border-accent);
}

.settings-field textarea {
  resize: vertical;
}

.settings-actions {
  display: flex;
  gap: var(--gap);
  margin-top: 16px;
}

/* Utility classes */
.hidden { display: none !important; }
</style>
</head>
<body>
<div id="app">

  <!-- Sidebar -->
  <div id="sidebar">
    <div id="sidebar-header">
      <input type="text" id="search-box" placeholder="search conversations..." autocomplete="off" spellcheck="false">
    </div>
    <div id="filters"></div>
    <div id="conv-list"></div>
    <div id="sidebar-footer">
      <span class="status" id="db-status">no database loaded</span>
    </div>
  </div>

  <!-- Main content -->
  <div id="main">
    <div id="main-header">
      <h2 id="conv-title">memex</h2>
      <div id="main-actions"></div>
    </div>
    <div id="messages">
      <div id="loading">loading...</div>
    </div>
    <div id="input-area" class="hidden">
      <textarea id="message-input" rows="1" placeholder="add a note..."></textarea>
      <button class="btn btn-primary" id="send-btn" onclick="sendMessage()">send</button>
    </div>
  </div>

  <!-- Timeline bar -->
  <div id="timeline">
    <span id="timeline-start" class="timeline-label"></span>
    <canvas id="timeline-canvas"></canvas>
    <span id="timeline-end" class="timeline-label"></span>
  </div>

</div>

<!-- Settings overlay -->
<div id="settings-overlay">
  <div id="settings-panel">
    <h3>settings</h3>
    <div class="settings-field">
      <label for="setting-api-key">Anthropic API key</label>
      <input type="password" id="setting-api-key" placeholder="sk-ant-..." autocomplete="off" spellcheck="false">
    </div>
    <div class="settings-field">
      <label for="setting-model">Model</label>
      <input type="text" id="setting-model" placeholder="claude-sonnet-4-6" autocomplete="off" spellcheck="false">
    </div>
    <div class="settings-field">
      <label for="setting-system-prompt">System prompt (optional)</label>
      <textarea id="setting-system-prompt" rows="4" placeholder="You are a helpful assistant..."></textarea>
    </div>
    <div class="settings-actions">
      <button class="btn btn-primary" onclick="saveSettings()">save</button>
      <button class="btn" onclick="toggleSettings()">close</button>
    </div>
  </div>
</div>

<!-- File picker / drop zone -->
<div id="drop-zone">
  <div id="drop-zone-inner">
    <p>drop a .db file here</p>
    <p style="font-size: var(--font-size-sm); color: var(--text-muted);">or</p>
    <button class="btn btn-primary" onclick="document.getElementById(&quot;file-input&quot;).click()">choose file</button>
  </div>
  <input type="file" id="file-input" accept=".db,.sqlite,.sqlite3">
</div>

<script src="https://cdn.jsdelivr.net/npm/sql.js@1.14.0/dist/sql-wasm.js"></script>
<script>
/* -- globals --------------------------------------------------------- */
var db = null;
var WASM_URL = "https://cdn.jsdelivr.net/npm/sql.js@1.14.0/dist/sql-wasm.wasm";

/* -- query helpers --------------------------------------------------- */

/**
 * Run a SELECT query and return an array of plain objects.
 * @param {string} sql - SQL query string
 * @param {Object|Array} [params] - Bind parameters
 * @returns {Array<Object>} Array of row objects
 */
function query(sql, params) {
  if (!db) throw new Error("No database loaded");
  var stmt = db.prepare(sql);
  try {
    if (params) stmt.bind(params);
    var results = [];
    while (stmt.step()) {
      results.push(stmt.getAsObject());
    }
    return results;
  } finally {
    stmt.free();
  }
}

/**
 * Run a write statement (INSERT, UPDATE, DELETE).
 * @param {string} sql - SQL statement
 * @param {Object|Array} [params] - Bind parameters
 */
function exec(sql, params) {
  if (!db) throw new Error("No database loaded");
  if (params) {
    db.run(sql, params);
  } else {
    db.run(sql);
  }
}

/* -- DB loading cascade ---------------------------------------------- */

/**
 * Initialize the application: load sql.js and attempt to open a database.
 *
 * Loading cascade:
 * 1. Check for ?db=path URL parameter
 * 2. Try fetching ./conversations.db
 * 3. Fall back to file picker (drag-and-drop + input)
 */
async function initApp() {
  var SQL = await initSqlJs({
    locateFile: function() { return WASM_URL; }
  });

  // 1. Check URL parameter
  var urlParams = new URLSearchParams(window.location.search);
  var dbParam = urlParams.get("db");

  if (dbParam) {
    try {
      var buf = await fetchDb(dbParam);
      db = new SQL.Database(new Uint8Array(buf));
      onDbLoaded();
      return;
    } catch (e) {
      console.warn("Failed to load DB from ?db= param:", e.message);
    }
  }

  // 2. Try default path
  try {
    var buf2 = await fetchDb("./conversations.db");
    db = new SQL.Database(new Uint8Array(buf2));
    onDbLoaded();
    return;
  } catch (e) {
    console.warn("No conversations.db found:", e.message);
  }

  // 3. Fall back to file picker
  showFilePicker(SQL);
}

/**
 * Fetch a database file and return its ArrayBuffer.
 * @param {string} url - URL to fetch
 * @returns {Promise<ArrayBuffer>}
 */
async function fetchDb(url) {
  var resp = await fetch(url);
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  return await resp.arrayBuffer();
}

/**
 * Show the drag-and-drop file picker overlay.
 * @param {Object} SQL - Initialized sql.js module
 */
function showFilePicker(SQL) {
  var dropZone = document.getElementById("drop-zone");
  var fileInput = document.getElementById("file-input");
  var loading = document.getElementById("loading");

  loading.textContent = "no database found";
  dropZone.classList.add("visible");

  function handleFile(file) {
    var reader = new FileReader();
    reader.onload = function() {
      db = new SQL.Database(new Uint8Array(reader.result));
      dropZone.classList.remove("visible");
      onDbLoaded();
    };
    reader.readAsArrayBuffer(file);
  }

  fileInput.addEventListener("change", function(e) {
    if (e.target.files.length > 0) handleFile(e.target.files[0]);
  });

  dropZone.addEventListener("dragover", function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });

  dropZone.addEventListener("drop", function(e) {
    e.preventDefault();
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
  });
}

/* -- state ----------------------------------------------------------- */
var activeFilters = { source: null, tag: null, starred: false, dateFrom: null, dateTo: null };
var activeConvId = null;
var searchTimer = null;
var searchWired = false;
var totalConvCount = 0;
var timelineData = [];
var timelineSelection = null;

/* -- helpers --------------------------------------------------------- */

/**
 * XSS-safe HTML escaping.
 * @param {string} s - Raw string
 * @returns {string} Escaped HTML string
 */
function esc(s) {
  if (s == null) return "";
  var d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

/**
 * Format an ISO date string to a short display format.
 * @param {string} iso - ISO date string
 * @returns {string} Formatted date
 */
function fmtDate(iso) {
  if (!iso) return "";
  try {
    var d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch (e) {
    return String(iso).substring(0, 10);
  }
}

/* -- app lifecycle --------------------------------------------------- */

/** Called after a database is successfully loaded. */
function onDbLoaded() {
  var status = document.getElementById("db-status");
  var loading = document.getElementById("loading");

  /* Update status */
  var countRow = query("SELECT count(*) AS n FROM conversations");
  totalConvCount = countRow.length > 0 ? countRow[0].n : 0;
  status.textContent = totalConvCount + " conversation" + (totalConvCount !== 1 ? "s" : "");
  status.style.color = "var(--success)";
  loading.textContent = "select a conversation";

  /* Render filter chips */
  renderFilters();

  /* Initialize timeline (stub called, filled in Task 4) */
  initTimeline();

  /* Load conversations */
  loadConversations();

  /* Wire up debounced search (once only) */
  if (!searchWired) {
    var searchBox = document.getElementById("search-box");
    searchBox.addEventListener("input", function() {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function() {
        loadConversations();
      }, 200);
    });
    searchWired = true;
  }

  /* Load settings from localStorage */
  loadSettings();
}

/**
 * Render source chips, tag chips (top 10), and starred toggle.
 * Click toggles activeFilters and reloads the conversation list.
 *
 * All user-provided strings are escaped via esc() before insertion
 * to prevent XSS. The esc() function uses textContent assignment
 * on a detached element, which is a standard safe escaping pattern.
 */
function renderFilters() {
  var container = document.getElementById("filters");
  var chips = [];

  /* Source chips */
  var sources = query("SELECT DISTINCT source FROM conversations WHERE source IS NOT NULL AND source != '' ORDER BY source");
  for (var i = 0; i < sources.length; i++) {
    var src = sources[i].source;
    var cls = activeFilters.source === src ? "filter-chip active" : "filter-chip";
    chips.push({cls: cls, filter: "source", value: src, label: src});
  }

  /* Tag chips (top 10 by frequency) */
  var tags = query("SELECT tag, count(*) AS n FROM tags GROUP BY tag ORDER BY n DESC LIMIT 10");
  for (var j = 0; j < tags.length; j++) {
    var tag = tags[j].tag;
    var cls2 = activeFilters.tag === tag ? "filter-chip active" : "filter-chip";
    chips.push({cls: cls2, filter: "tag", value: tag, label: "#" + tag});
  }

  /* Starred toggle */
  var starCls = activeFilters.starred ? "filter-chip active" : "filter-chip";
  chips.push({cls: starCls, filter: "starred", value: "", label: "starred"});

  /* Build DOM safely */
  container.textContent = "";
  for (var k = 0; k < chips.length; k++) {
    var chip = chips[k];
    var span = document.createElement("span");
    span.className = chip.cls;
    span.setAttribute("data-filter", chip.filter);
    span.setAttribute("data-value", chip.value);
    span.textContent = chip.label;
    span.addEventListener("click", function() {
      var filterType = this.getAttribute("data-filter");
      var filterValue = this.getAttribute("data-value");
      if (filterType === "source") {
        activeFilters.source = activeFilters.source === filterValue ? null : filterValue;
      } else if (filterType === "tag") {
        activeFilters.tag = activeFilters.tag === filterValue ? null : filterValue;
      } else if (filterType === "starred") {
        activeFilters.starred = !activeFilters.starred;
      }
      renderFilters();
      loadConversations();
    });
    container.appendChild(span);
  }
}

/**
 * Load the conversation list into the sidebar.
 *
 * Builds SQL dynamically based on search term and active filters.
 * All user-provided strings are escaped via esc() before insertion
 * to prevent XSS. Uses parameterized queries for SQL injection safety.
 */
function loadConversations() {
  var searchBox = document.getElementById("search-box");
  var searchTerm = searchBox ? searchBox.value.trim() : "";
  var convList = document.getElementById("conv-list");

  var sql, params = [];

  if (searchTerm) {
    sql = "SELECT DISTINCT c.id, c.title, c.source, c.model, c.message_count, c.updated_at, c.starred_at FROM conversations c JOIN messages m ON m.conversation_id = c.id WHERE m.content LIKE '%' || ? || '%'";
    params.push(searchTerm);
  } else {
    sql = "SELECT c.id, c.title, c.source, c.model, c.message_count, c.updated_at, c.starred_at FROM conversations c WHERE 1=1";
  }

  /* Apply filters */
  if (activeFilters.source) {
    sql += " AND c.source = ?";
    params.push(activeFilters.source);
  }
  if (activeFilters.tag) {
    sql += " AND EXISTS (SELECT 1 FROM tags t WHERE t.conversation_id = c.id AND t.tag = ?)";
    params.push(activeFilters.tag);
  }
  if (activeFilters.starred) {
    sql += " AND c.starred_at IS NOT NULL";
  }
  if (activeFilters.dateFrom) {
    sql += " AND c.updated_at >= ?";
    params.push(activeFilters.dateFrom);
  }
  if (activeFilters.dateTo) {
    sql += " AND c.updated_at <= ?";
    params.push(activeFilters.dateTo);
  }

  sql += " ORDER BY c.updated_at DESC LIMIT 500";

  var rows;
  try {
    rows = query(sql, params.length > 0 ? params : undefined);
  } catch (e) {
    console.error("loadConversations query error:", e);
    rows = [];
  }

  /* Build DOM safely using createElement + textContent */
  convList.textContent = "";
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i];
    var title = r.title || "Untitled";
    var meta = [];
    if (r.source) meta.push(r.source);
    if (r.message_count != null) meta.push(r.message_count + " msgs");
    if (r.updated_at) meta.push(fmtDate(r.updated_at));

    var item = document.createElement("div");
    item.className = "conv-item";
    item.setAttribute("data-id", r.id);

    var titleDiv = document.createElement("div");
    titleDiv.className = "conv-item-title";
    titleDiv.textContent = (r.starred_at ? "* " : "") + title;
    item.appendChild(titleDiv);

    var metaDiv = document.createElement("div");
    metaDiv.className = "conv-item-meta";
    metaDiv.textContent = meta.join(" \u00b7 ");
    item.appendChild(metaDiv);

    (function(convId) {
      item.addEventListener("click", function() { openConversation(convId); });
    })(r.id);

    convList.appendChild(item);
  }

  if (rows.length === 0) {
    var empty = document.createElement("div");
    empty.style.cssText = "padding: var(--gap); color: var(--text-muted); font-size: var(--font-size-sm);";
    empty.textContent = "no conversations found";
    convList.appendChild(empty);
  }

  /* Update footer count (uses cached totalConvCount from onDbLoaded) */
  var status = document.getElementById("db-status");
  if (status) {
    if (searchTerm || activeFilters.source || activeFilters.tag || activeFilters.starred) {
      status.textContent = rows.length + " / " + totalConvCount + " conversations";
    } else {
      status.textContent = totalConvCount + " conversation" + (totalConvCount !== 1 ? "s" : "");
    }
  }
}

/**
 * Open a conversation by ID and render it in the main panel.
 * @param {string} convId - Conversation ID
 */
function openConversation(convId) {
  activeConvId = convId;

  /* Highlight active sidebar item */
  var items = document.querySelectorAll(".conv-item");
  for (var i = 0; i < items.length; i++) {
    items[i].classList.toggle("active", items[i].getAttribute("data-id") === convId);
  }

  /* Query conversation metadata */
  var convRows = query("SELECT * FROM conversations WHERE id = ?", [convId]);
  if (convRows.length === 0) return;
  var conv = convRows[0];

  /* Query messages ordered by created_at */
  var messages = query(
    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
    [convId]
  );

  /* Query tags */
  var tagRows = query("SELECT tag FROM tags WHERE conversation_id = ?", [convId]);
  var tags = [];
  for (var t = 0; t < tagRows.length; t++) tags.push(tagRows[t].tag);

  renderConversation(conv, messages, tags);
}

/**
 * Render conversation header, messages, and input area.
 * @param {Object} conv - Conversation row
 * @param {Array} messages - Message rows
 * @param {Array<string>} tags - Tag strings
 */
function renderConversation(conv, messages, tags) {
  var container = document.getElementById("messages");
  var titleEl = document.getElementById("conv-title");
  var inputArea = document.getElementById("input-area");

  /* Update header title */
  titleEl.textContent = conv.title || "Untitled";

  /* Build messages HTML */
  var html = "";

  /* Conversation header block */
  html += '<div class="conv-header">';
  html += "<h2>" + esc(conv.title || "Untitled") + "</h2>";
  var meta = [];
  if (conv.source) meta.push(esc(conv.source));
  if (conv.model) meta.push(esc(conv.model));
  meta.push(messages.length + " messages");
  if (conv.created_at) meta.push(fmtDate(conv.created_at));
  html += '<div class="conv-header-meta">' + meta.join(" &middot; ") + "</div>";
  if (tags.length > 0) {
    html += '<div class="conv-header-tags">';
    for (var t = 0; t < tags.length; t++) {
      html += '<span class="conv-tag">' + esc(tags[t]) + "</span>";
    }
    html += "</div>";
  }
  html += "</div>";

  /* Render each message */
  for (var i = 0; i < messages.length; i++) {
    var msg = messages[i];
    var role = msg.role || "unknown";
    var roleCls = (role === "user" || role === "assistant" || role === "system") ? role : "";
    html += '<div class="message ' + roleCls + '">';
    html += '<div class="message-role">' + esc(role) + "</div>";
    html += '<div class="message-content">';

    /* Parse content blocks from JSON */
    var blocks = [];
    try {
      var parsed = JSON.parse(msg.content);
      if (Array.isArray(parsed)) {
        blocks = parsed;
      } else if (typeof parsed === "string") {
        blocks = [{ type: "text", text: parsed }];
      } else {
        blocks = [parsed];
      }
    } catch (e) {
      /* If not JSON, treat as plain text */
      blocks = [{ type: "text", text: String(msg.content || "") }];
    }

    html += renderContent(blocks);
    html += "</div></div>";
  }

  container.innerHTML = html;

  /* Show input area */
  inputArea.classList.remove("hidden");
}

/**
 * Render an array of content blocks to HTML.
 * @param {Array<Object>} blocks - Content blocks
 * @returns {string} HTML string
 */
function renderContent(blocks) {
  var parts = [];
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i];
    var btype = b.type || "";
    if (btype === "text" && b.text) {
      parts.push(renderMarkdown(b.text));
    } else if (btype === "media") {
      parts.push(renderMedia(b));
    }
    /* Skip tool_use, tool_result, thinking */
  }
  return parts.join("");
}

/**
 * Render a media content block to HTML.
 * @param {Object} block - Media block with media_type, url, data, filename
 * @returns {string} HTML string
 */
function renderMedia(block) {
  var mt = block.media_type || "";
  var url = block.url || "";
  var data = block.data || "";
  var fname = block.filename || "";

  /* Build data URI if we have base64 data and no url */
  if (!url && data && mt) {
    url = "data:" + mt + ";base64," + data;
  }

  if (!url) {
    return fname ? "<span>[" + esc(fname) + "]</span>" : "";
  }

  if (mt.startsWith("image/")) {
    return '<img src="' + esc(url) + '" alt="' + esc(fname || "image") + '" loading="lazy">';
  }
  if (mt.startsWith("audio/")) {
    return '<audio controls src="' + esc(url) + '"></audio>';
  }
  if (mt.startsWith("video/")) {
    return '<video controls src="' + esc(url) + '"></video>';
  }
  return '<a href="' + esc(url) + '" target="_blank">' + esc(fname || "attachment") + "</a>";
}

/**
 * Lightweight markdown-to-HTML renderer.
 * Handles fenced code blocks, inline code, headings, bold, italic,
 * images, links, horizontal rules, unordered lists, and paragraphs.
 * @param {string} text - Raw markdown text
 * @returns {string} HTML string
 */
function renderMarkdown(text) {
  if (!text) return "";

  /* Escape HTML entities first */
  text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  /* Extract fenced code blocks and replace with placeholders */
  var codeBlocks = [];
  text = text.replace(/```(\w*)\\n([\s\S]*?)```/g, function(m, lang, code) {
    var idx = codeBlocks.length;
    var cls = lang ? ' class="language-' + lang + '"' : "";
    codeBlocks.push("<pre><code" + cls + ">" + code + "</code></pre>");
    return "\x00CB" + idx + "\x00";
  });

  /* Extract inline code and replace with placeholders */
  var inlineCodes = [];
  text = text.replace(/`([^`\\n]+)`/g, function(m, code) {
    var idx = inlineCodes.length;
    inlineCodes.push("<code>" + code + "</code>");
    return "\x00IC" + idx + "\x00";
  });

  /* Headings */
  text = text.replace(/^#### (.+)$/gm, "<h4>$1</h4>");
  text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");

  /* Horizontal rules */
  text = text.replace(/^---+$/gm, "<hr>");

  /* Unordered lists */
  text = text.replace(/^[*-] (.+)$/gm, "<li>$1</li>");
  text = text.replace(/((?:<li>.*<\/li>\\n?)+)/g, "<ul>$1</ul>");

  /* Images: ![alt](url) */
  text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" loading="lazy">');

  /* Links: [text](url) */
  text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

  /* Bold+italic: ***text*** */
  text = text.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");

  /* Bold: **text** */
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  /* Italic: *text* */
  text = text.replace(/\*(.+?)\*/g, "<em>$1</em>");

  /* Paragraph breaks: double newline */
  text = text.replace(/\\n\\n+/g, "</p><p>");

  /* Single newlines to <br> (but not inside block elements) */
  text = text.replace(/\\n/g, "<br>");

  /* Wrap in paragraph if not starting with block element */
  if (!/^\s*<(h[1-4]|pre|ul|hr|p)/.test(text)) {
    text = "<p>" + text + "</p>";
  }

  /* Restore inline code placeholders */
  text = text.replace(/\x00IC(\d+)\x00/g, function(m, idx) {
    return inlineCodes[parseInt(idx)];
  });

  /* Restore code block placeholders */
  text = text.replace(/\x00CB(\d+)\x00/g, function(m, idx) {
    return codeBlocks[parseInt(idx)];
  });

  return text;
}

/** Initialize the timeline bar at the bottom. */
function initTimeline() {
  if (totalConvCount === 0) return;

  /* Query monthly conversation counts */
  var rows = query(
    "SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS count FROM conversations GROUP BY month ORDER BY month"
  );
  if (rows.length === 0) return;

  timelineData = rows;
  timelineSelection = null;

  /* Set start/end labels */
  var startLabel = document.getElementById("timeline-start");
  var endLabel = document.getElementById("timeline-end");
  startLabel.textContent = rows[0].month;
  endLabel.textContent = rows[rows.length - 1].month;

  drawTimeline();

  /* Mouse interaction state */
  var canvas = document.getElementById("timeline-canvas");
  var dragging = false;
  var dragStartIdx = -1;

  canvas.addEventListener("mousedown", function(e) {
    if (timelineData.length === 0) return;
    dragging = true;
    var rect = canvas.getBoundingClientRect();
    var x = e.clientX - rect.left;
    var barW = rect.width / timelineData.length;
    dragStartIdx = Math.min(Math.floor(x / barW), timelineData.length - 1);
    dragStartIdx = Math.max(0, dragStartIdx);
    timelineSelection = { start: dragStartIdx, end: dragStartIdx };
    drawTimeline();
  });

  canvas.addEventListener("mousemove", function(e) {
    if (!dragging || timelineData.length === 0) return;
    var rect = canvas.getBoundingClientRect();
    var x = e.clientX - rect.left;
    var barW = rect.width / timelineData.length;
    var idx = Math.min(Math.floor(x / barW), timelineData.length - 1);
    idx = Math.max(0, idx);
    timelineSelection = { start: Math.min(dragStartIdx, idx), end: Math.max(dragStartIdx, idx) };
    drawTimeline();
  });

  canvas.addEventListener("mouseup", function() {
    if (!dragging) return;
    dragging = false;
    if (!timelineSelection || timelineData.length === 0) return;
    var fromMonth = timelineData[timelineSelection.start].month;
    var toMonth = timelineData[timelineSelection.end].month;
    activeFilters.dateFrom = fromMonth + "-01";
    /* Set dateTo to end of month */
    var toYear = parseInt(toMonth.substring(0, 4));
    var toMon = parseInt(toMonth.substring(5, 7));
    if (toMon === 12) { toYear++; toMon = 1; } else { toMon++; }
    var nextMonth = toYear + "-" + (toMon < 10 ? "0" + toMon : toMon) + "-01";
    activeFilters.dateTo = nextMonth;
    loadConversations();
  });

  canvas.addEventListener("dblclick", function() {
    timelineSelection = null;
    activeFilters.dateFrom = null;
    activeFilters.dateTo = null;
    drawTimeline();
    loadConversations();
  });

  /* Redraw on resize */
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(function() {
      drawTimeline();
    }).observe(canvas.parentElement);
  }
}

/**
 * Draw the timeline bar chart on the canvas.
 * Each month is a vertical bar, height proportional to count/maxCount.
 * Selected range bars use accent color, others use border color.
 * Handles devicePixelRatio for crisp rendering.
 */
function drawTimeline() {
  var canvas = document.getElementById("timeline-canvas");
  if (!canvas || timelineData.length === 0) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;

  /* Size canvas to match CSS layout */
  var rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  var w = rect.width;
  var h = rect.height;
  var n = timelineData.length;
  var barW = w / n;
  var gap = Math.max(1, barW * 0.15);
  var margin = 2;

  /* Find max count */
  var maxCount = 0;
  for (var i = 0; i < n; i++) {
    if (timelineData[i].count > maxCount) maxCount = timelineData[i].count;
  }
  if (maxCount === 0) return;

  /* Read colors from CSS custom properties */
  var style = getComputedStyle(canvas);
  var barColor = style.getPropertyValue("--border").trim() || "#30363d";
  var accentColor = style.getPropertyValue("--text-accent").trim() || "#58a6ff";

  ctx.save();
  ctx.scale(dpr, dpr);

  for (var j = 0; j < n; j++) {
    var barH = (timelineData[j].count / maxCount) * (h - margin * 2);
    var x = j * barW + gap / 2;
    var y = h - margin - barH;

    var selected = timelineSelection &&
      j >= timelineSelection.start && j <= timelineSelection.end;
    ctx.fillStyle = selected ? accentColor : barColor;
    ctx.fillRect(x, y, barW - gap, barH);
  }

  ctx.restore();
}

/**
 * Send a message via Anthropic API (resume chat).
 * Requires API key configured in settings (anthropic-dangerous-direct-browser-access).
 */
async function sendMessage() {
  if (!db || !activeConvId) return;

  var apiKey = localStorage.getItem("memex_api_key") || "";
  if (!apiKey) {
    toggleSettings();
    return;
  }

  var input = document.getElementById("message-input");
  var sendBtn = document.getElementById("send-btn");
  var userText = input.value.trim();
  if (!userText) return;

  /* Disable input during streaming */
  input.value = "";
  sendBtn.disabled = true;

  var model = localStorage.getItem("memex_model") || "claude-sonnet-4-6";
  var systemPrompt = localStorage.getItem("memex_system_prompt") || "";

  /* Build message history from DB */
  var dbMessages = query(
    "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
    [activeConvId]
  );
  var history = [];
  for (var i = 0; i < dbMessages.length; i++) {
    var msg = dbMessages[i];
    var text = "";
    try {
      var parsed = JSON.parse(msg.content);
      if (Array.isArray(parsed)) {
        for (var j = 0; j < parsed.length; j++) {
          if (parsed[j].type === "text" && parsed[j].text) text += parsed[j].text;
        }
      } else if (typeof parsed === "string") {
        text = parsed;
      }
    } catch (e) {
      text = String(msg.content || "");
    }
    if (text && (msg.role === "user" || msg.role === "assistant")) {
      history.push({ role: msg.role, content: text });
    }
  }

  /* Add user's new message */
  history.push({ role: "user", content: userText });

  /* Get the last message ID for parent_id */
  var lastMsgRows = query(
    "SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
    [activeConvId]
  );
  var parentId = lastMsgRows.length > 0 ? lastMsgRows[0].id : null;

  /* INSERT user message into DB */
  var userMsgId = crypto.randomUUID();
  var now = new Date().toISOString();
  var userContent = JSON.stringify([{ type: "text", text: userText }]);
  exec(
    "INSERT INTO messages (conversation_id, id, role, content, parent_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
    [activeConvId, userMsgId, "user", userContent, parentId, now]
  );

  /* Render user message in the conversation view */
  var container = document.getElementById("messages");
  var userDiv = document.createElement("div");
  userDiv.className = "message user";
  userDiv.innerHTML = '<div class="message-role">user</div><div class="message-content">' + renderMarkdown(userText) + "</div>";
  container.appendChild(userDiv);

  /* Create assistant message div for streaming */
  var assistDiv = document.createElement("div");
  assistDiv.className = "message assistant";
  assistDiv.innerHTML = '<div class="message-role">assistant</div><div class="message-content"></div>';
  container.appendChild(assistDiv);
  var assistContent = assistDiv.querySelector(".message-content");
  container.scrollTop = container.scrollHeight;

  /* Build request body */
  var body = { model: model, max_tokens: 4096, stream: true, messages: history };
  if (systemPrompt) body.system = systemPrompt;

  var accumulated = "";
  try {
    var response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true"
      },
      body: JSON.stringify(body)
    });

    if (!response.ok) {
      var errText = await response.text();
      throw new Error("API error " + response.status + ": " + errText);
    }

    /* Read SSE stream */
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";

    while (true) {
      var result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });

      var lines = buffer.split("\\n");
      buffer = lines.pop();

      for (var k = 0; k < lines.length; k++) {
        var line = lines[k].trim();
        if (!line.startsWith("data: ")) continue;
        var data = line.substring(6);
        if (data === "[DONE]") continue;
        try {
          var evt = JSON.parse(data);
          if (evt.type === "content_block_delta" && evt.delta && evt.delta.type === "text_delta") {
            accumulated += evt.delta.text;
            assistContent.innerHTML = renderMarkdown(accumulated);
            container.scrollTop = container.scrollHeight;
          }
        } catch (e) {
          /* Skip unparseable SSE lines */
        }
      }
    }
  } catch (err) {
    if (!accumulated) {
      assistContent.innerHTML = '<span style="color: var(--danger);">Error: ' + esc(err.message) + "</span>";
    }
    console.error("sendMessage error:", err);
  }

  /* INSERT assistant message into DB */
  if (accumulated) {
    var assistMsgId = crypto.randomUUID();
    var assistNow = new Date().toISOString();
    var assistContentJson = JSON.stringify([{ type: "text", text: accumulated }]);
    exec(
      "INSERT INTO messages (conversation_id, id, role, content, parent_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
      [activeConvId, assistMsgId, "assistant", assistContentJson, userMsgId, assistNow]
    );

    /* Update conversation metadata */
    exec(
      "UPDATE conversations SET message_count = (SELECT count(*) FROM messages WHERE conversation_id = ?), updated_at = ? WHERE id = ?",
      [activeConvId, assistNow, activeConvId]
    );
  }

  sendBtn.disabled = false;
}

/** Download the current database as a .db file. */
function downloadDb() {
  if (!db) return;
  var data = db.export();
  var blob = new Blob([data], { type: "application/octet-stream" });
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = "conversations.db";
  a.click();
  URL.revokeObjectURL(url);
}

/** Load settings from localStorage into form fields. */
function loadSettings() {
  var apiKey = localStorage.getItem("memex_api_key") || "";
  var model = localStorage.getItem("memex_model") || "";
  var systemPrompt = localStorage.getItem("memex_system_prompt") || "";
  document.getElementById("setting-api-key").value = apiKey;
  document.getElementById("setting-model").value = model;
  document.getElementById("setting-system-prompt").value = systemPrompt;
}

/** Save settings from form fields to localStorage. */
function saveSettings() {
  var apiKey = document.getElementById("setting-api-key").value.trim();
  var model = document.getElementById("setting-model").value.trim();
  var systemPrompt = document.getElementById("setting-system-prompt").value.trim();
  localStorage.setItem("memex_api_key", apiKey);
  localStorage.setItem("memex_model", model);
  localStorage.setItem("memex_system_prompt", systemPrompt);
  toggleSettings();
}

/** Toggle the settings overlay visibility. */
function toggleSettings() {
  var overlay = document.getElementById("settings-overlay");
  overlay.classList.toggle("visible");
}

/* -- boot ------------------------------------------------------------ */
initApp().catch(function(err) {
  console.error("initApp failed:", err);
  var loading = document.getElementById("loading");
  if (loading) loading.textContent = "error: " + err.message;
});
</script>
</body>
</html>'''
