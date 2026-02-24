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
