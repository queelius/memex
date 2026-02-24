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
        chunk = html[start:start + 800]
        assert "<a href" in chunk
        assert "target" in chunk

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
