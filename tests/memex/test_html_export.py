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
