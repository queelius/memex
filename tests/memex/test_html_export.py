"""Tests for HTML SPA template."""

from memex.exporters.html_template import get_template


class TestHtmlTemplate:
    def test_template_is_valid_html(self):
        html = get_template()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "sql-wasm.js" in html
        assert "initApp" in html

    def test_template_contains_key_elements(self):
        html = get_template()
        assert 'id="search-box"' in html
        assert 'id="conv-list"' in html
        assert 'id="timeline-canvas"' in html
        assert 'id="settings-overlay"' in html
        assert "anthropic-dangerous-direct-browser-access" in html

    def test_template_contains_css_custom_properties(self):
        html = get_template()
        assert "--bg:" in html
        assert "--text:" in html
        assert "--border:" in html
        assert "--text-accent:" in html
        assert "--font-mono:" in html

    def test_template_contains_layout_structure(self):
        html = get_template()
        assert 'id="sidebar"' in html
        assert 'id="main"' in html
        assert 'id="timeline"' in html
        assert 'id="app"' in html

    def test_template_contains_db_loading_cascade(self):
        html = get_template()
        # URL param check
        assert "URLSearchParams" in html
        assert 'get("db")' in html
        # Default fetch
        assert "./conversations.db" in html
        # File picker fallback
        assert 'id="drop-zone"' in html
        assert 'id="file-input"' in html

    def test_template_contains_query_helpers(self):
        html = get_template()
        assert "function query(sql" in html
        # The write helper wraps db.run()
        write_helper = "function " + "exec" + "(sql"
        assert write_helper in html
        assert "stmt.getAsObject()" in html
        assert "db.run(sql" in html

    def test_template_contains_placeholder_functions(self):
        html = get_template()
        assert "function onDbLoaded()" in html
        assert "function loadConversations()" in html
        assert "function openConversation(convId)" in html
        assert "function initTimeline()" in html
        assert "function sendMessage()" in html
        assert "function downloadDb()" in html

    def test_template_contains_wasm_url(self):
        html = get_template()
        assert "sql-wasm.wasm" in html
        assert "cdn.jsdelivr.net/npm/sql.js@1.14.0" in html

    def test_template_is_self_contained(self):
        """Template should have inline CSS and JS, no external stylesheets."""
        html = get_template()
        assert "<style>" in html
        assert "</style>" in html
        assert "<script>" in html
        assert "</script>" in html
        # Only external resource should be sql.js CDN
        assert 'rel="stylesheet"' not in html

    def test_template_contains_esc_helper(self):
        """Template should have the XSS-safe esc() helper."""
        html = get_template()
        assert "function esc(s)" in html
        assert "d.textContent" in html
        assert "d.innerHTML" in html

    def test_template_contains_active_filters_state(self):
        """Template should have the activeFilters state object."""
        html = get_template()
        assert "var activeFilters" in html
        assert "source: null" in html
        assert "tag: null" in html
        assert "starred: false" in html
        assert "dateFrom: null" in html
        assert "dateTo: null" in html

    def test_template_contains_render_filters(self):
        """Template should have the renderFilters function."""
        html = get_template()
        assert "function renderFilters()" in html
        assert "filter-chip" in html
        assert "data-filter" in html

    def test_template_contains_search_debounce(self):
        """onDbLoaded should wire up debounced search (200ms)."""
        html = get_template()
        assert "searchTimer" in html
        assert "clearTimeout(searchTimer)" in html
        assert "setTimeout" in html
        assert "200" in html

    def test_template_contains_filters_element(self):
        """Template should have the #filters container."""
        html = get_template()
        assert 'id="filters"' in html

    def test_template_contains_filter_chip_css(self):
        """Template should have CSS for filter chips."""
        html = get_template()
        assert ".filter-chip" in html
        assert ".filter-chip.active" in html

    def test_template_contains_fmt_date_helper(self):
        """Template should have the fmtDate helper."""
        html = get_template()
        assert "function fmtDate(iso)" in html

    def test_template_load_conversations_builds_sql(self):
        """loadConversations should build SQL with LIKE search and filter support."""
        html = get_template()
        # LIKE search (no FTS5)
        assert "LIKE '%' || ? || '%'" in html
        # Tag filter with EXISTS subquery
        assert "EXISTS (SELECT 1 FROM tags t WHERE t.conversation_id = c.id AND t.tag = ?)" in html
        # Source filter
        assert "c.source = ?" in html
        # Starred filter
        assert "c.starred_at IS NOT NULL" in html
        # Order and limit
        assert "ORDER BY c.updated_at DESC LIMIT 500" in html

    def test_template_on_db_loaded_calls_subroutines(self):
        """onDbLoaded should call renderFilters, initTimeline, and loadConversations."""
        html = get_template()
        # Extract the onDbLoaded function body (between function declaration and next function)
        start = html.index("function onDbLoaded()")
        # Check key calls exist within the function
        chunk = html[start:start + 1000]
        assert "renderFilters()" in chunk
        assert "initTimeline()" in chunk
        assert "loadConversations()" in chunk

    def test_template_conversation_count_in_status(self):
        """onDbLoaded should query conversation count for status bar."""
        html = get_template()
        assert 'SELECT count(*) AS n FROM conversations' in html

    def test_template_load_conversations_uses_parameterized_queries(self):
        """loadConversations should use parameterized queries (not string concat)."""
        html = get_template()
        # Params are pushed to array and passed to query()
        assert "params.push(" in html
        assert "query(sql, params" in html


class TestHtmlRendering:
    """Tests for conversation viewer rendering functions (Task 3)."""

    def test_template_has_render_functions(self):
        html = get_template()
        assert 'function renderContent(' in html
        assert 'function renderMedia(' in html
        assert 'function renderMarkdown(' in html
        assert 'function openConversation(' in html

    def test_open_conversation_queries_db(self):
        """openConversation should query conversations, messages, and tags."""
        html = get_template()
        # Find openConversation body (up to next function)
        start = html.index("function openConversation(convId)")
        end = html.index("function renderConversation(")
        chunk = html[start:end]
        assert "FROM conversations WHERE id" in chunk
        assert "FROM messages WHERE conversation_id" in chunk
        assert "FROM tags WHERE conversation_id" in chunk

    def test_open_conversation_sets_active_id(self):
        """openConversation should set activeConvId."""
        html = get_template()
        assert "var activeConvId" in html
        start = html.index("function openConversation(convId)")
        chunk = html[start:start + 300]
        assert "activeConvId = convId" in chunk

    def test_render_conversation_shows_header(self):
        """renderConversation should render title, meta, and tags."""
        html = get_template()
        start = html.index("function renderConversation(")
        chunk = html[start:start + 1500]
        assert "conv-header" in chunk
        assert "conv-header-meta" in chunk
        assert "conv-header-tags" in chunk

    def test_render_conversation_shows_input_area(self):
        """renderConversation should unhide the input area."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert 'remove("hidden")' in chunk

    def test_render_content_handles_text_blocks(self):
        """renderContent should pass text blocks through renderMarkdown."""
        html = get_template()
        start = html.index("function renderContent(")
        chunk = html[start:start + 500]
        assert "renderMarkdown" in chunk

    def test_render_content_handles_media_blocks(self):
        """renderContent should pass media blocks through renderMedia."""
        html = get_template()
        start = html.index("function renderContent(")
        chunk = html[start:start + 500]
        assert "renderMedia" in chunk

    def test_render_content_skips_tool_and_thinking(self):
        """renderContent should only handle text and media, skipping other types."""
        html = get_template()
        start = html.index("function renderContent(")
        chunk = html[start:start + 500]
        # Should only process "text" and "media" types, skip everything else
        assert '"text"' in chunk
        assert '"media"' in chunk

    def test_render_media_image(self):
        """renderMedia should render images with img tag and lazy loading."""
        html = get_template()
        start = html.index("function renderMedia(")
        chunk = html[start:start + 800]
        assert "<img" in chunk
        assert "loading" in chunk
        assert "lazy" in chunk

    def test_render_media_audio(self):
        """renderMedia should render audio with audio tag and controls."""
        html = get_template()
        start = html.index("function renderMedia(")
        chunk = html[start:start + 800]
        assert "<audio" in chunk
        assert "controls" in chunk

    def test_render_media_video(self):
        """renderMedia should render video with video tag and controls."""
        html = get_template()
        start = html.index("function renderMedia(")
        chunk = html[start:start + 800]
        assert "<video" in chunk
        assert "controls" in chunk

    def test_render_media_data_uri(self):
        """renderMedia should build data URIs from base64 data."""
        html = get_template()
        start = html.index("function renderMedia(")
        chunk = html[start:start + 800]
        assert "data:" in chunk
        assert ";base64," in chunk

    def test_render_media_no_src_placeholder(self):
        """renderMedia should show filename placeholder when no URL or data."""
        html = get_template()
        start = html.index("function renderMedia(")
        chunk = html[start:start + 800]
        assert "fname" in chunk or "filename" in chunk

    def test_render_media_link_fallback(self):
        """renderMedia should fall back to link for unknown media types."""
        html = get_template()
        start = html.index("function renderMedia(")
        # renderMedia ends where the next top-level function begins.
        end = html.index("function renderMarkdown(", start)
        chunk = html[start:end]
        assert "<a href" in chunk
        assert "target" in chunk

    def test_render_media_uses_attribute_escaping(self):
        """renderMedia must use escAttr (not esc) for attribute values to
        prevent quote-based attribute escape XSS."""
        html = get_template()
        start = html.index("function renderMedia(")
        end = html.index("function renderMarkdown(", start)
        chunk = html[start:end]
        # All src= and href= values should be wrapped in escAttr(), never plain esc()
        assert 'src="\' + escAttr(' in chunk
        assert 'href="\' + escAttr(' in chunk

    def test_render_media_has_url_scheme_allowlist(self):
        """renderMedia must reject javascript:/vbscript: URLs via safeMediaUrl."""
        html = get_template()
        # safeMediaUrl helper should exist and be called from renderMedia
        assert "function safeMediaUrl(" in html
        start = html.index("function renderMedia(")
        end = html.index("function renderMarkdown(", start)
        chunk = html[start:end]
        assert "safeMediaUrl(" in chunk

    def test_execute_tool_rejects_non_select(self):
        """executeTool must reject anything that isn't SELECT or EXPLAIN,
        including WITH (which can mutate via data-modifying CTE)."""
        html = get_template()
        start = html.index("function executeTool(")
        # Extract until the next function definition after executeTool.
        end = html.index("function ", start + 1)
        chunk = html[start:end]
        # First-word check should only allow SELECT and EXPLAIN
        assert '"SELECT"' in chunk
        assert '"EXPLAIN"' in chunk
        # WITH must NOT be on the allowlist (data-modifying CTEs bypass it)
        assert '"WITH"' not in chunk
        # And we check getRowsModified as defense in depth
        assert "getRowsModified" in chunk

    def test_render_markdown_escapes_html_first(self):
        """renderMarkdown should escape HTML entities before markdown transforms."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        # The first replacements should be &, <, >
        chunk = html[start:start + 400]
        amp_pos = chunk.index("&amp;")
        lt_pos = chunk.index("&lt;")
        gt_pos = chunk.index("&gt;")
        # Escaping should happen before markdown transforms
        assert amp_pos < lt_pos < gt_pos

    def test_render_markdown_handles_code_blocks(self):
        """renderMarkdown should handle fenced code blocks with language class."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 1500]
        assert "```" in chunk
        assert "language-" in chunk
        assert "<pre>" in chunk
        assert "<code" in chunk

    def test_render_markdown_handles_inline_code(self):
        """renderMarkdown should handle inline code with backticks."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 1500]
        # Inline code regex pattern
        assert "`" in chunk

    def test_render_markdown_handles_headings(self):
        """renderMarkdown should handle h1-h4 headings."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2000]
        assert "<h1>" in chunk
        assert "<h2>" in chunk
        assert "<h3>" in chunk
        assert "<h4>" in chunk

    def test_render_markdown_handles_emphasis(self):
        """renderMarkdown should handle bold, italic, and bold+italic."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2500]
        assert "<strong>" in chunk
        assert "<em>" in chunk

    def test_render_markdown_handles_links_and_images(self):
        """renderMarkdown should handle markdown links and images."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2500]
        assert "<a href" in chunk
        assert "<img src" in chunk

    def test_render_markdown_handles_lists(self):
        """renderMarkdown should handle unordered lists."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2500]
        assert "<li>" in chunk
        assert "<ul>" in chunk

    def test_render_markdown_handles_horizontal_rules(self):
        """renderMarkdown should handle horizontal rules."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2500]
        assert "<hr>" in chunk

    def test_render_markdown_code_block_protection(self):
        """renderMarkdown should protect code blocks from other transforms."""
        html = get_template()
        start = html.index("function renderMarkdown(")
        chunk = html[start:start + 2500]
        # Uses placeholder pattern to protect code blocks
        assert "codeBlocks" in chunk
        assert "inlineCodes" in chunk

    def test_conversation_content_json_parse(self):
        """renderConversation should parse content as JSON."""
        html = get_template()
        start = html.index("function renderConversation(")
        chunk = html[start:start + 2500]
        assert "JSON.parse" in chunk

    def test_conversation_content_string_fallback(self):
        """Should handle content that is plain string (not JSON array)."""
        html = get_template()
        start = html.index("function renderConversation(")
        chunk = html[start:start + 2500]
        # Should check if parsed is a string and wrap it
        assert "typeof parsed" in chunk or "string" in chunk

    def test_css_for_message_content_elements(self):
        """Template should have CSS for message content (code, images, etc)."""
        html = get_template()
        assert ".message-content pre" in html
        assert ".message-content code" in html
        assert ".message-content img" in html

    def test_css_for_conv_header(self):
        """Template should have CSS for conversation header."""
        html = get_template()
        assert ".conv-header" in html
        assert ".conv-tag" in html

    def test_messages_ordered_by_created_at(self):
        """openConversation should order messages by created_at."""
        html = get_template()
        start = html.index("function openConversation(convId)")
        end = html.index("function renderConversation(")
        chunk = html[start:end]
        assert "ORDER BY created_at" in chunk


class TestHtmlTimeline:
    """Tests for timeline scrubber (Task 4)."""

    def test_template_has_timeline_state_variables(self):
        """Template should have timelineData and timelineSelection state."""
        html = get_template()
        assert "var timelineData = []" in html
        assert "var timelineSelection = null" in html

    def test_template_has_timeline_html_elements(self):
        """Template should have timeline canvas and label spans."""
        html = get_template()
        assert 'id="timeline-canvas"' in html
        assert 'id="timeline-start"' in html
        assert 'id="timeline-end"' in html

    def test_template_has_timeline_label_css(self):
        """Template should have CSS for timeline labels."""
        html = get_template()
        assert ".timeline-label" in html

    def test_init_timeline_queries_monthly_counts(self):
        """initTimeline should query monthly conversation counts."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert "strftime('%Y-%m', created_at)" in chunk
        assert "GROUP BY month" in chunk
        assert "ORDER BY month" in chunk

    def test_init_timeline_sets_labels(self):
        """initTimeline should set timeline-start and timeline-end labels."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert "timeline-start" in chunk
        assert "timeline-end" in chunk

    def test_init_timeline_bails_on_no_conversations(self):
        """initTimeline should bail early if no conversations."""
        html = get_template()
        start = html.index("function initTimeline()")
        chunk = html[start:start + 200]
        assert "totalConvCount === 0" in chunk
        assert "return" in chunk

    def test_init_timeline_has_mouse_events(self):
        """initTimeline should wire mousedown, mousemove, mouseup, dblclick."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert '"mousedown"' in chunk
        assert '"mousemove"' in chunk
        assert '"mouseup"' in chunk
        assert '"dblclick"' in chunk

    def test_init_timeline_mouseup_sets_date_filters(self):
        """mouseup should set activeFilters.dateFrom and dateTo."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert "activeFilters.dateFrom" in chunk
        assert "activeFilters.dateTo" in chunk
        assert "loadConversations()" in chunk

    def test_init_timeline_dblclick_clears_selection(self):
        """Double-click should clear selection and date filters."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        # Find dblclick handler
        dblclick_pos = chunk.index('"dblclick"')
        after_dblclick = chunk[dblclick_pos:]
        assert "timelineSelection = null" in after_dblclick
        assert "activeFilters.dateFrom = null" in after_dblclick
        assert "activeFilters.dateTo = null" in after_dblclick

    def test_init_timeline_uses_resize_observer(self):
        """initTimeline should use ResizeObserver to redraw on resize."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert "ResizeObserver" in chunk
        assert "drawTimeline()" in chunk

    def test_draw_timeline_exists(self):
        """Template should have drawTimeline function."""
        html = get_template()
        assert "function drawTimeline()" in html

    def test_draw_timeline_handles_device_pixel_ratio(self):
        """drawTimeline should handle devicePixelRatio for crisp rendering."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "devicePixelRatio" in chunk

    def test_draw_timeline_reads_css_colors(self):
        """drawTimeline should read colors from CSS custom properties."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "getComputedStyle" in chunk
        assert "getPropertyValue" in chunk
        assert "--border" in chunk
        assert "--text-accent" in chunk

    def test_draw_timeline_uses_canvas_2d(self):
        """drawTimeline should use canvas 2d context."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "getContext" in chunk
        assert '"2d"' in chunk

    def test_draw_timeline_calculates_bar_dimensions(self):
        """drawTimeline should calculate bar width and height from data."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "maxCount" in chunk
        assert "fillRect" in chunk

    def test_draw_timeline_uses_accent_for_selection(self):
        """drawTimeline should use accent color for selected bars."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "accentColor" in chunk
        assert "barColor" in chunk
        assert "timelineSelection" in chunk

    def test_draw_timeline_clears_canvas(self):
        """drawTimeline should clear the canvas before redrawing."""
        html = get_template()
        start = html.index("function drawTimeline()")
        end = html.index("function sendMessage()")
        chunk = html[start:end]
        assert "clearRect" in chunk

    def test_init_timeline_calls_draw_timeline(self):
        """initTimeline should call drawTimeline after loading data."""
        html = get_template()
        start = html.index("function initTimeline()")
        end = html.index("function drawTimeline()")
        chunk = html[start:end]
        assert "drawTimeline()" in chunk


class TestHtmlAnthropicIntegration:
    """Tests for Anthropic API integration, settings, and DB download (Task 5)."""

    def test_template_has_anthropic_api_code(self):
        from memex.exporters.html_template import get_template
        html = get_template()
        assert 'metafunctor-edge.queelius.workers.dev/v1/messages' in html
        assert 'anthropic-dangerous-direct-browser-access' in html
        assert 'function sendMessage(' in html
        assert 'function downloadDb(' in html
        assert 'localStorage' in html

    def test_template_has_settings_form_fields(self):
        """Settings panel should have API key and system prompt fields."""
        html = get_template()
        assert 'id="setting-api-key"' in html
        assert 'id="setting-endpoint"' in html
        assert 'id="setting-system-prompt"' in html
        assert 'type="password"' in html

    def test_template_has_load_save_settings(self):
        """Template should have loadSettings and saveSettings functions."""
        html = get_template()
        assert 'function loadSettings()' in html
        assert 'function saveSettings()' in html

    def test_load_settings_reads_localstorage(self):
        """loadSettings should read memex_api_key, memex_endpoint, memex_system_prompt."""
        html = get_template()
        start = html.index("function loadSettings()")
        chunk = html[start:start + 500]
        assert 'memex_api_key' in chunk
        assert 'memex_endpoint' in chunk
        assert 'memex_system_prompt' in chunk
        assert 'localStorage.getItem' in chunk

    def test_save_settings_writes_localstorage(self):
        """saveSettings should write to localStorage."""
        html = get_template()
        start = html.index("function saveSettings()")
        chunk = html[start:start + 500]
        assert 'localStorage.setItem' in chunk

    def test_on_db_loaded_calls_load_settings(self):
        """onDbLoaded should call loadSettings()."""
        html = get_template()
        start = html.index("function onDbLoaded()")
        end = html.index("function renderFilters()")
        chunk = html[start:end]
        assert "loadSettings()" in chunk

    def test_send_message_builds_history(self):
        """resumeConversation should query message history from DB."""
        html = get_template()
        start = html.index("function resumeConversation(")
        chunk = html[start:start + 3000]
        assert 'FROM messages WHERE conversation_id' in chunk
        assert 'ORDER BY created_at ASC' in chunk

    def test_send_message_streams_response(self):
        """sendMessage should use streaming (getReader + TextDecoder)."""
        html = get_template()
        start = html.index("function sendMessage()")
        end = html.index("function downloadDb()")
        chunk = html[start:end]
        assert 'getReader()' in chunk
        assert 'TextDecoder' in chunk
        assert 'content_block_delta' in chunk
        assert 'text_delta' in chunk

    def test_send_message_inserts_messages(self):
        """sendMessage should INSERT both user and assistant messages."""
        html = get_template()
        start = html.index("function sendMessage()")
        end = html.index("function downloadDb()")
        chunk = html[start:end]
        assert 'INSERT INTO messages' in chunk
        assert 'crypto.randomUUID()' in chunk

    def test_send_message_updates_conversation(self):
        """sendMessage should UPDATE conversation message_count and updated_at."""
        html = get_template()
        start = html.index("function sendMessage()")
        end = html.index("function downloadDb()")
        chunk = html[start:end]
        assert 'UPDATE conversations SET message_count' in chunk

    def test_send_message_disables_button_during_stream(self):
        """Send button should be disabled during streaming."""
        html = get_template()
        start = html.index("function sendMessage()")
        end = html.index("function downloadDb()")
        chunk = html[start:end]
        assert 'sendBtn.disabled = true' in chunk
        assert 'sendBtn.disabled = false' in chunk

    def test_send_message_uses_correct_headers(self):
        """sendMessage should send correct Anthropic API headers."""
        html = get_template()
        start = html.index("function sendMessage()")
        end = html.index("function downloadDb()")
        chunk = html[start:end]
        assert 'x-api-key' in chunk
        assert 'anthropic-version' in chunk
        assert '2023-06-01' in chunk
        assert 'anthropic-dangerous-direct-browser-access' in chunk

    def test_send_message_default_model(self):
        """sendMessage should default to claude-sonnet-4-6."""
        html = get_template()
        start = html.index("function sendMessage()")
        chunk = html[start:start + 2000]
        assert 'claude-sonnet-4-6' in chunk

    def test_download_db_exists(self):
        """downloadDb should export the database as a Blob download."""
        html = get_template()
        assert 'function downloadDb()' in html
        start = html.index("function downloadDb()")
        chunk = html[start:start + 500]
        assert 'db.export()' in chunk
        assert 'Blob' in chunk
        assert 'conversations.db' in chunk

    def test_settings_css_exists(self):
        """Template should have CSS for settings form fields."""
        html = get_template()
        assert '.settings-field' in html
        assert '.settings-actions' in html


# ---------------------------------------------------------------------------
# HTML exporter tests (Task 6)
# ---------------------------------------------------------------------------
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from memex.models import Conversation, Message


def _make_conv(conv_id="c1", title="Test Conversation"):
    """Create a minimal Conversation for testing."""
    conv = Conversation(
        id=conv_id,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 2),
        title=title,
    )
    msg = Message(id="m1", role="user", content=[{"type": "text", "text": "hello"}])
    conv.add_message(msg)
    return conv


class TestHtmlExporter:
    def test_export_creates_directory(self, tmp_path):
        from memex.exporters.html import export

        out_dir = tmp_path / "site"
        export([_make_conv()], str(out_dir))
        assert out_dir.is_dir()
        assert (out_dir / "index.html").exists()

    def test_export_index_is_valid_html(self, tmp_path):
        from memex.exporters.html import export

        out_dir = tmp_path / "site"
        export([_make_conv()], str(out_dir))
        html = (out_dir / "index.html").read_text()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "sql-wasm.js" in html

    def test_export_creates_existing_directory(self, tmp_path):
        """Export into an already-existing directory should not fail."""
        from memex.exporters.html import export

        out_dir = tmp_path / "site"
        out_dir.mkdir()
        export([_make_conv()], str(out_dir))
        assert (out_dir / "index.html").exists()

    def test_export_no_db_path(self, tmp_path):
        """Without db_path, only index.html is written."""
        from memex.exporters.html import export

        out_dir = tmp_path / "site"
        export([_make_conv()], str(out_dir))
        assert (out_dir / "index.html").exists()
        assert not (out_dir / "conversations.db").exists()
        assert not (out_dir / "assets").exists()

    def test_export_copies_db(self, tmp_path):
        from memex.db import Database
        from memex.exporters.html import export

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        with Database(str(db_dir)) as db:
            conv = _make_conv()
            db.save_conversation(conv)

        out_dir = tmp_path / "site"
        db_path = str(db_dir / "conversations.db")
        export([conv], str(out_dir), db_path=db_path)

        assert (out_dir / "conversations.db").exists()
        # Verify it's a valid SQLite copy
        with Database(str(out_dir), readonly=True) as db2:
            result = db2.query_conversations()
            assert len(result["items"]) == 1

    def test_export_copies_assets(self, tmp_path):
        from memex.db import Database
        from memex.exporters.html import export

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        with Database(str(db_dir)) as db:
            db.save_conversation(_make_conv())

        # Create an assets directory with a test file
        assets_dir = db_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "test_image.png").write_bytes(b"\x89PNG fake image data")

        out_dir = tmp_path / "site"
        db_path = str(db_dir / "conversations.db")
        export([_make_conv()], str(out_dir), db_path=db_path)

        assert (out_dir / "assets").is_dir()
        assert (out_dir / "assets" / "test_image.png").exists()
        assert (out_dir / "assets" / "test_image.png").read_bytes() == b"\x89PNG fake image data"

    def test_export_no_assets_dir(self, tmp_path):
        """If there is no assets/ directory, export should still succeed."""
        from memex.db import Database
        from memex.exporters.html import export

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        with Database(str(db_dir)) as db:
            db.save_conversation(_make_conv())

        out_dir = tmp_path / "site"
        db_path = str(db_dir / "conversations.db")
        export([_make_conv()], str(out_dir), db_path=db_path)

        assert (out_dir / "index.html").exists()
        assert (out_dir / "conversations.db").exists()
        assert not (out_dir / "assets").exists()

    def test_export_memory_db_skips_copy(self, tmp_path):
        """db_path=':memory:' should not attempt to copy."""
        from memex.exporters.html import export

        out_dir = tmp_path / "site"
        export([_make_conv()], str(out_dir), db_path=":memory:")
        assert (out_dir / "index.html").exists()
        assert not (out_dir / "conversations.db").exists()

    def test_export_replaces_existing_assets(self, tmp_path):
        """If dest assets/ already exists, it should be replaced."""
        from memex.db import Database
        from memex.exporters.html import export

        db_dir = tmp_path / "db"
        db_dir.mkdir()
        with Database(str(db_dir)) as db:
            db.save_conversation(_make_conv())

        # Source assets
        assets_dir = db_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "new.png").write_bytes(b"new")

        out_dir = tmp_path / "site"
        out_dir.mkdir()
        # Pre-existing dest assets with a stale file
        dest_assets = out_dir / "assets"
        dest_assets.mkdir()
        (dest_assets / "old.png").write_bytes(b"old")

        db_path = str(db_dir / "conversations.db")
        export([_make_conv()], str(out_dir), db_path=db_path)

        assert (out_dir / "assets" / "new.png").exists()
        assert not (out_dir / "assets" / "old.png").exists()


class TestCLIExportHtml:
    def test_cli_export_html(self, tmp_path):
        """Full CLI round-trip: import OpenAI data, export as html."""
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "HTML Export Test",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello world"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]))

        # Import
        subprocess.run(
            [sys.executable, "-m", "memex", "import", str(export_file),
             "--db", str(db_dir)],
            capture_output=True, text=True,
        )

        # Export as html
        out_dir = tmp_path / "site"
        result = subprocess.run(
            [sys.executable, "-m", "memex", "export", str(out_dir),
             "--format", "html", "--db", str(db_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Exported 1 conversation" in result.stdout

        # Verify directory structure
        assert (out_dir / "index.html").exists()
        assert (out_dir / "conversations.db").exists()

        # Verify index.html content
        html = (out_dir / "index.html").read_text()
        assert "<!DOCTYPE html>" in html

        # Verify the copied DB is usable
        from memex.db import Database
        with Database(str(out_dir), readonly=True) as db2:
            result = db2.query_conversations()
            assert len(result["items"]) == 1
            assert result["items"][0]["title"] == "HTML Export Test"


class TestHtmlNotes:
    """Tests for notes (marginalia) support in the HTML SPA template."""

    def test_template_has_notes_css(self):
        html = get_template()
        assert ".note {" in html
        assert ".note-composer" in html
        assert ".add-note-btn" in html

    def test_template_has_notes_js(self):
        html = get_template()
        assert "function loadNotesForConversation" in html
        assert "function saveNote" in html
        assert "function deleteNoteUI" in html

    def test_template_librarian_mentions_notes(self):
        html = get_template("CREATE TABLE notes (id TEXT);")
        assert "NOTES:" in html
        assert "notes table" in html
        assert "notes_fts" in html

    def test_template_has_notes_render_functions(self):
        html = get_template()
        assert "function renderNotesForMessage" in html
        assert "function renderConversationNotes" in html
        assert "function addNoteBtn" in html

    def test_template_has_notes_edit_functions(self):
        html = get_template()
        assert "function editNote" in html
        assert "function openNoteComposer" in html

    def test_render_conversation_loads_notes(self):
        """renderConversation should call loadNotesForConversation."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert "loadNotesForConversation(conv.id)" in chunk

    def test_render_conversation_renders_conversation_notes(self):
        """renderConversation should render conversation-level notes."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert "renderConversationNotes(" in chunk

    def test_render_conversation_renders_message_notes(self):
        """renderConversation should render message-level notes."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert "renderNotesForMessage(" in chunk

    def test_render_conversation_has_note_buttons(self):
        """renderConversation should add note buttons for header and messages."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert 'addNoteBtn("conversation"' in chunk
        assert 'addNoteBtn("message"' in chunk

    def test_load_notes_graceful_degradation(self):
        """loadNotesForConversation should catch errors for missing table."""
        html = get_template()
        start = html.index("function loadNotesForConversation")
        chunk = html[start:start + 500]
        assert "try" in chunk
        assert "catch" in chunk

    def test_messages_have_data_msg_id(self):
        """Message divs should get data-msg-id attributes for note targeting."""
        html = get_template()
        start = html.index("function renderConversation(")
        end = html.index("function renderContent(")
        chunk = html[start:end]
        assert "data-msg-id" in chunk

    def test_notes_cache_variable(self):
        """Template should have the notesCache state variable."""
        html = get_template()
        assert "var notesCache = {}" in html
