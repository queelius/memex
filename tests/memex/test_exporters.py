"""Tests for memex exporters: Markdown, JSON."""
import json
from datetime import datetime

from memex.models import Conversation, Message, text_block, media_block
from memex.exporters.markdown import export as md_export
from memex.exporters.json_export import export as json_export


def _make_conv(id="c1", title="Test Chat"):
    now = datetime(2024, 6, 15)
    conv = Conversation(id=id, created_at=now, updated_at=now, title=title, source="test")
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(Message(id="m2", role="assistant", content=[text_block("hi there")], parent_id="m1"))
    return conv


# ---------- Markdown ----------

class TestMarkdownExporter:
    def test_single_conversation(self, tmp_path):
        out = tmp_path / "out.md"
        md_export([_make_conv()], str(out))
        content = out.read_text()
        assert "# Test Chat" in content
        assert "hello" in content
        assert "hi there" in content

    def test_multiple_conversations(self, tmp_path):
        out = tmp_path / "out.md"
        md_export([_make_conv("c1", "First"), _make_conv("c2", "Second")], str(out))
        content = out.read_text()
        assert "# First" in content
        assert "# Second" in content

    def test_source_included(self, tmp_path):
        out = tmp_path / "out.md"
        md_export([_make_conv()], str(out))
        content = out.read_text()
        assert "*Source: test*" in content

    def test_roles_in_output(self, tmp_path):
        out = tmp_path / "out.md"
        md_export([_make_conv()], str(out))
        content = out.read_text()
        assert "**user**:" in content
        assert "**assistant**:" in content

    def test_no_title_uses_id(self, tmp_path):
        conv = _make_conv()
        conv.title = None
        out = tmp_path / "out.md"
        md_export([conv], str(out))
        content = out.read_text()
        assert "# c1" in content

    def test_empty_list(self, tmp_path):
        out = tmp_path / "out.md"
        md_export([], str(out))
        assert out.read_text() == ""

    def test_branching_conversation(self, tmp_path):
        now = datetime(2024, 6, 15)
        conv = Conversation(id="c1", created_at=now, updated_at=now, title="Branch")
        conv.add_message(Message(id="m1", role="user", content=[text_block("start")]))
        conv.add_message(Message(id="m2a", role="assistant", content=[text_block("reply A")], parent_id="m1"))
        conv.add_message(Message(id="m2b", role="assistant", content=[text_block("reply B")], parent_id="m1"))
        out = tmp_path / "out.md"
        md_export([conv], str(out))
        content = out.read_text()
        assert "reply A" in content
        assert "reply B" in content
        # Should have separator between paths
        assert content.count("---") >= 2


# ---------- JSON ----------

class TestJSONExporter:
    def test_single_conversation(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_make_conv()], str(out))
        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "c1"
        assert data[0]["title"] == "Test Chat"
        assert len(data[0]["messages"]) == 2

    def test_messages_structure(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_make_conv()], str(out))
        data = json.loads(out.read_text())
        msg = data[0]["messages"][0]
        assert "id" in msg
        assert "role" in msg
        assert "content" in msg
        assert "parent_id" in msg

    def test_content_blocks_preserved(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_make_conv()], str(out))
        data = json.loads(out.read_text())
        msg = data[0]["messages"][0]
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][0]["text"] == "hello"

    def test_metadata_fields(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_make_conv()], str(out))
        data = json.loads(out.read_text())
        assert data[0]["source"] == "test"
        assert "created_at" in data[0]
        assert "updated_at" in data[0]
        assert "tags" in data[0]

    def test_multiple_conversations(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_make_conv("c1"), _make_conv("c2")], str(out))
        data = json.loads(out.read_text())
        assert len(data) == 2

    def test_empty_list(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([], str(out))
        data = json.loads(out.read_text())
        assert data == []

    def test_roundtrip_content(self, tmp_path):
        """Content blocks should be valid JSON after export."""
        now = datetime(2024, 6, 15)
        conv = Conversation(id="c1", created_at=now, updated_at=now, title="Multi")
        conv.add_message(Message(id="m1", role="user", content=[
            text_block("hello"),
            media_block("image/png", url="http://example.com/img.png"),
        ]))
        out = tmp_path / "out.json"
        json_export([conv], str(out))
        data = json.loads(out.read_text())
        msg = data[0]["messages"][0]
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][1]["type"] == "media"
        assert msg["content"][1]["url"] == "http://example.com/img.png"
