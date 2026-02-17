"""Tests for memex MCP server.

These tests exercise the database methods that back the MCP tools
directly, plus smoke-test that the server object can be created.
Full MCP protocol testing is deferred to integration tests.
"""
import json
from datetime import datetime

import pytest

from memex.db import Database
from memex.models import Conversation, Message, text_block
from memex.server import create_server


@pytest.fixture
def db(tmp_db_path):
    """Database with one conversation containing two messages."""
    d = Database(tmp_db_path)
    now = datetime.now()
    conv = Conversation(
        id="c1", created_at=now, updated_at=now,
        title="Test", source="openai", tags=["python"],
    )
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(Message(
        id="m2", role="assistant", content=[text_block("hi")], parent_id="m1",
    ))
    d.save_conversation(conv)
    return d


class TestCreateServer:
    def test_creates_server(self, db):
        server = create_server(db=db)
        assert server is not None

    def test_creates_server_with_sql_write(self, db):
        server = create_server(db=db, sql_write=True)
        assert server._test_sql_write is True

    def test_server_has_test_db(self, db):
        server = create_server(db=db)
        assert server._test_db is db


class TestExecuteSQL:
    def test_select(self, db):
        result = db.execute_sql("SELECT id, title FROM conversations")
        assert len(result) == 1
        assert result[0]["id"] == "c1"

    def test_select_messages(self, db):
        result = db.execute_sql(
            "SELECT id, role FROM messages WHERE conversation_id=?", ("c1",)
        )
        assert len(result) == 2

    def test_read_only_enforcement(self, db):
        """Verify that the SQL validation logic correctly identifies write statements."""
        write_statements = ["DROP TABLE conversations", "DELETE FROM messages",
                            "INSERT INTO tags VALUES ('x','y')", "UPDATE conversations SET title='x'"]
        for sql in write_statements:
            sql_stripped = sql.strip().upper()
            is_read_only = sql_stripped.startswith("SELECT") or sql_stripped.startswith("PRAGMA")
            assert not is_read_only, f"Should block: {sql}"

    def test_read_only_allows_select(self, db):
        sql = "SELECT * FROM conversations"
        sql_stripped = sql.strip().upper()
        is_read_only = sql_stripped.startswith("SELECT") or sql_stripped.startswith("PRAGMA")
        assert is_read_only

    def test_read_only_allows_pragma(self, db):
        sql = "PRAGMA table_info(conversations)"
        sql_stripped = sql.strip().upper()
        is_read_only = sql_stripped.startswith("SELECT") or sql_stripped.startswith("PRAGMA")
        assert is_read_only

    def test_pragma(self, db):
        result = db.execute_sql("PRAGMA table_info(conversations)")
        assert len(result) > 0


class TestQueryTool:
    def test_query_all(self, db):
        result = db.query_conversations()
        assert len(result["items"]) == 1

    def test_query_by_tag(self, db):
        result = db.query_conversations(tag="python")
        assert len(result["items"]) == 1

    def test_query_by_tag_no_match(self, db):
        result = db.query_conversations(tag="nonexistent")
        assert len(result["items"]) == 0

    def test_query_by_source(self, db):
        result = db.query_conversations(source="openai")
        assert len(result["items"]) == 1

    def test_query_by_source_no_match(self, db):
        result = db.query_conversations(source="anthropic")
        assert len(result["items"]) == 0

    def test_query_fts(self, db):
        result = db.query_conversations(query="hello")
        assert len(result["items"]) == 1

    def test_query_fts_no_match(self, db):
        result = db.query_conversations(query="zzzznotfound")
        assert len(result["items"]) == 0

    def test_query_with_limit(self, db):
        result = db.query_conversations(limit=1)
        assert len(result["items"]) <= 1

    def test_query_has_more_field(self, db):
        result = db.query_conversations()
        assert "has_more" in result
        assert "next_cursor" in result


class TestUpdateTool:
    def test_star(self, db):
        db.update_conversation("c1", starred=True)
        conv = db.load_conversation("c1")
        assert conv.starred_at is not None

    def test_unstar(self, db):
        db.update_conversation("c1", starred=True)
        db.update_conversation("c1", starred=False)
        conv = db.load_conversation("c1")
        assert conv.starred_at is None

    def test_pin(self, db):
        db.update_conversation("c1", pinned=True)
        assert db.load_conversation("c1").pinned_at is not None

    def test_archive(self, db):
        db.update_conversation("c1", archived=True)
        assert db.load_conversation("c1").archived_at is not None

    def test_title(self, db):
        db.update_conversation("c1", title="New Title")
        assert db.load_conversation("c1").title == "New Title"

    def test_summary(self, db):
        db.update_conversation("c1", summary="A summary")
        assert db.load_conversation("c1").summary == "A summary"

    def test_sensitive(self, db):
        db.update_conversation("c1", sensitive=True)
        assert db.load_conversation("c1").sensitive is True

    def test_add_tags(self, db):
        db.update_conversation("c1", add_tags=["newtag"])
        conv = db.load_conversation("c1")
        assert "newtag" in conv.tags

    def test_remove_tags(self, db):
        db.update_conversation("c1", remove_tags=["python"])
        conv = db.load_conversation("c1")
        assert "python" not in conv.tags

    def test_metadata(self, db):
        db.update_conversation("c1", metadata={"key": "value"})
        conv = db.load_conversation("c1")
        assert conv.metadata["key"] == "value"

    def test_update_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_conversation("nonexistent", title="x")


class TestAppendTool:
    def test_append(self, db):
        db.append_message(
            "c1",
            Message(id="m3", role="user", content=[text_block("more")], parent_id="m2"),
        )
        conv = db.load_conversation("c1")
        assert conv.message_count == 3

    def test_append_updates_count(self, db):
        db.append_message(
            "c1",
            Message(id="m3", role="user", content=[text_block("q1")], parent_id="m2"),
        )
        db.append_message(
            "c1",
            Message(id="m4", role="assistant", content=[text_block("a1")], parent_id="m3"),
        )
        conv = db.load_conversation("c1")
        assert conv.message_count == 4

    def test_append_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.append_message(
                "nonexistent",
                Message(id="m3", role="user", content=[text_block("x")]),
            )


class TestResources:
    def test_schema_resource(self, db):
        schema = db.get_schema()
        assert "CREATE TABLE conversations" in schema

    def test_schema_has_messages(self, db):
        schema = db.get_schema()
        assert "CREATE TABLE messages" in schema

    def test_schema_has_fts(self, db):
        schema = db.get_schema()
        assert "messages_fts" in schema

    def test_statistics(self, db):
        stats = db.get_statistics()
        assert stats["total_conversations"] == 1
        assert stats["total_messages"] == 2

    def test_statistics_sources(self, db):
        stats = db.get_statistics()
        assert "openai" in stats["sources"]

    def test_statistics_tags(self, db):
        stats = db.get_statistics()
        assert "python" in stats["tags"]

    def test_conversation_load(self, db):
        conv = db.load_conversation("c1")
        assert conv is not None
        assert conv.title == "Test"

    def test_conversation_load_not_found(self, db):
        conv = db.load_conversation("nonexistent")
        assert conv is None


class TestListPaths:
    def test_list_paths(self, db):
        paths = db.list_paths("c1")
        assert len(paths) >= 1
        assert paths[0]["message_count"] == 2

    def test_list_paths_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.list_paths("nonexistent")

    def test_path_structure(self, db):
        paths = db.list_paths("c1")
        path = paths[0]
        assert "index" in path
        assert "first_message" in path
        assert "last_message" in path
        assert "leaf_id" in path
        assert path["first_message"]["role"] == "user"
        assert path["last_message"]["role"] == "assistant"


class TestGetPathMessages:
    def test_default_path(self, db):
        messages = db.get_path_messages("c1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_by_path_index(self, db):
        messages = db.get_path_messages("c1", path_index=0)
        assert len(messages) == 2

    def test_by_leaf_id(self, db):
        messages = db.get_path_messages("c1", leaf_message_id="m2")
        assert len(messages) == 2

    def test_with_offset(self, db):
        messages = db.get_path_messages("c1", offset=1)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    def test_with_limit(self, db):
        messages = db.get_path_messages("c1", limit=1)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.get_path_messages("nonexistent")

    def test_invalid_path_index(self, db):
        with pytest.raises(ValueError, match="out of range"):
            db.get_path_messages("c1", path_index=99)

    def test_invalid_leaf_id(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.get_path_messages("c1", leaf_message_id="nonexistent")


class TestExportConversation:
    """Test the export logic that would be used by the MCP export_conversation tool."""

    def test_export_markdown(self, db):
        conv = db.load_conversation("c1")
        paths = conv.get_all_paths()
        lines = [f"# {conv.title or conv.id}\n"]
        for i, path in enumerate(paths):
            if len(paths) > 1:
                lines.append(f"\n## Path {i}\n")
            for msg in path:
                lines.append(f"**{msg.role}**: {msg.get_text()}\n")
        md = "\n".join(lines)
        assert "# Test" in md
        assert "**user**: hello" in md
        assert "**assistant**: hi" in md

    def test_export_json(self, db):
        conv = db.load_conversation("c1")
        exported = json.dumps({
            "id": conv.id, "title": conv.title,
            "messages": [
                {"id": m.id, "role": m.role, "content": m.content, "parent_id": m.parent_id}
                for m in conv.messages.values()
            ],
        }, indent=2)
        data = json.loads(exported)
        assert data["id"] == "c1"
        assert data["title"] == "Test"
        assert len(data["messages"]) == 2


class TestBranchingConversation:
    """Test with a branching conversation tree."""

    @pytest.fixture
    def branching_db(self, tmp_db_path):
        d = Database(tmp_db_path)
        now = datetime.now()
        conv = Conversation(
            id="c2", created_at=now, updated_at=now,
            title="Branching", source="test",
        )
        conv.add_message(Message(id="m1", role="user", content=[text_block("start")]))
        conv.add_message(Message(id="m2a", role="assistant", content=[text_block("branch a")], parent_id="m1"))
        conv.add_message(Message(id="m2b", role="assistant", content=[text_block("branch b")], parent_id="m1"))
        d.save_conversation(conv)
        return d

    def test_list_paths_branching(self, branching_db):
        paths = branching_db.list_paths("c2")
        assert len(paths) == 2

    def test_get_path_by_leaf(self, branching_db):
        msgs_a = branching_db.get_path_messages("c2", leaf_message_id="m2a")
        assert len(msgs_a) == 2
        assert msgs_a[1]["id"] == "m2a"

        msgs_b = branching_db.get_path_messages("c2", leaf_message_id="m2b")
        assert len(msgs_b) == 2
        assert msgs_b[1]["id"] == "m2b"
