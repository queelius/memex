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
  width: 100%;
  height: 32px;
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
    <canvas id="timeline-canvas"></canvas>
  </div>

</div>

<!-- Settings overlay -->
<div id="settings-overlay">
  <div id="settings-panel">
    <h3>settings</h3>
    <p>Settings panel placeholder.</p>
    <button class="btn" onclick="toggleSettings()">close</button>
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
  text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code) {
    var idx = codeBlocks.length;
    var cls = lang ? ' class="language-' + lang + '"' : "";
    codeBlocks.push("<pre><code" + cls + ">" + code + "</code></pre>");
    return "\x00CB" + idx + "\x00";
  });

  /* Extract inline code and replace with placeholders */
  var inlineCodes = [];
  text = text.replace(/`([^`\n]+)`/g, function(m, code) {
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
  text = text.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

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
  text = text.replace(/\n\n+/g, "</p><p>");

  /* Single newlines to <br> (but not inside block elements) */
  text = text.replace(/\n/g, "<br>");

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
  // TODO: implemented in Task 4
}

/**
 * Send a message via Anthropic API (resume chat).
 * Requires API key configured in settings (anthropic-dangerous-direct-browser-access).
 */
function sendMessage() {
  // TODO: implemented in Task 5
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
