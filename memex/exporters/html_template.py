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
  white-space: pre-wrap;
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

/* -- placeholder functions (filled in by later tasks) ---------------- */

/** Called after a database is successfully loaded. */
function onDbLoaded() {
  var status = document.getElementById("db-status");
  var loading = document.getElementById("loading");
  status.textContent = "database loaded";
  status.style.color = "var(--success)";
  loading.textContent = "select a conversation";
  loadConversations();
}

/** Load the conversation list into the sidebar. */
function loadConversations() {
  // TODO: implemented in Task 2
}

/**
 * Open a conversation by ID and render it in the main panel.
 * @param {string} convId - Conversation ID
 */
function openConversation(convId) {
  // TODO: implemented in Task 3
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
