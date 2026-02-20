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
from memex.mcp import create_server, _conv_metadata


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


@pytest.fixture
def multi_db(tmp_db_path):
    """Database with multiple conversations for bulk/search tests."""
    d = Database(tmp_db_path)
    for i in range(1, 4):
        now = datetime(2024, 1, i)
        conv = Conversation(
            id=f"c{i}", created_at=now, updated_at=now,
            title=f"Chat {i}", source="openai" if i <= 2 else "anthropic",
            model="gpt-4", tags=["python"] if i % 2 == 0 else ["rust"],
        )
        conv.add_message(
            Message(id="m1", role="user", content=[text_block(f"topic {i}")])
        )
        conv.add_message(
            Message(
                id="m2", role="assistant",
                content=[text_block(f"answer {i}")], parent_id="m1",
            )
        )
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

    def test_server_has_six_tools(self, db):
        server = create_server(db=db)
        tool_names = [t.name for t in server._tool_manager._tools.values()]
        assert sorted(tool_names) == sorted([
            "execute_sql", "query_conversations", "get_conversation",
            "search_messages", "update_conversations", "append_message",
        ])

    def test_server_has_two_resources(self, db):
        server = create_server(db=db)
        # Resources are registered — we check the count
        resource_names = list(server._resource_manager._resources.keys())
        assert len(resource_names) == 2


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

    def test_pragma(self, db):
        result = db.execute_sql("PRAGMA table_info(conversations)")
        assert len(result) > 0


class TestQueryConversations:
    def test_query_all(self, db):
        result = db.query_conversations()
        assert len(result["items"]) == 1

    def test_query_has_tags_csv(self, db):
        result = db.query_conversations()
        assert "tags_csv" in result["items"][0]
        assert result["items"][0]["tags_csv"] == "python"

    def test_query_by_title(self, db):
        result = db.query_conversations(title="Test")
        assert len(result["items"]) == 1

    def test_query_by_title_no_match(self, db):
        result = db.query_conversations(title="nonexistent")
        assert len(result["items"]) == 0

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

    def test_query_has_pagination(self, db):
        result = db.query_conversations()
        assert "has_more" in result
        assert "next_cursor" in result


class TestGetConversation:
    """Test get_conversation through the DB methods it calls."""

    def test_metadata_mode(self, db):
        """id only → metadata + path summaries."""
        conv = db.load_conversation("c1")
        assert conv is not None
        meta = _conv_metadata(conv, db)
        assert meta["id"] == "c1"
        assert meta["title"] == "Test"
        assert meta["starred"] is False
        assert meta["pinned"] is False
        assert meta["archived"] is False
        assert meta["tags"] == ["python"]

    def test_metadata_paths(self, db):
        paths = db.list_paths("c1")
        assert len(paths) >= 1
        assert paths[0]["message_count"] == 2

    def test_messages_mode_by_index(self, db):
        messages = db.get_path_messages("c1", path_index=0)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_messages_mode_by_leaf(self, db):
        messages = db.get_path_messages("c1", leaf_message_id="m2")
        assert len(messages) == 2

    def test_messages_mode_with_offset(self, db):
        messages = db.get_path_messages("c1", offset=1)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"

    def test_messages_mode_with_limit(self, db):
        messages = db.get_path_messages("c1", limit=1)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_not_found(self, db):
        assert db.load_conversation("nonexistent") is None

    def test_invalid_path_index(self, db):
        with pytest.raises(ValueError, match="out of range"):
            db.get_path_messages("c1", path_index=99)

    def test_invalid_leaf_id(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.get_path_messages("c1", leaf_message_id="nonexistent")

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
        assert len(data["messages"]) == 2


class TestSearchMessages:
    def test_fts_search(self, multi_db):
        results = multi_db.search_messages("topic")
        assert len(results) >= 1
        assert all("message_id" in r for r in results)

    def test_phrase_search(self, multi_db):
        results = multi_db.search_messages("topic 2", mode="phrase")
        assert len(results) >= 1
        found = any("topic 2" in r["content"] for r in results)
        assert found

    def test_like_search(self, multi_db):
        results = multi_db.search_messages("%answer%", mode="like")
        assert len(results) >= 1

    def test_filter_by_conversation(self, multi_db):
        results = multi_db.search_messages("topic", conversation_id="c1")
        assert all(r["conversation_id"] == "c1" for r in results)

    def test_filter_by_role(self, multi_db):
        results = multi_db.search_messages("answer", role="assistant")
        assert all(r["role"] == "assistant" for r in results)

    def test_no_results(self, multi_db):
        results = multi_db.search_messages("zzz_nonexistent_zzz")
        assert len(results) == 0

    def test_context_messages(self, multi_db):
        results = multi_db.search_messages("topic 1")
        # With default context=1, get_context_messages should return neighbors
        assert len(results) >= 1
        ctx = multi_db.get_context_messages(
            results[0]["conversation_id"],
            results[0]["message_id"],
            context=1,
        )
        assert len(ctx) >= 1

    def test_invalid_mode(self, multi_db):
        with pytest.raises(ValueError, match="Invalid search mode"):
            multi_db.search_messages("test", mode="invalid")


class TestUpdateConversations:
    """Test bulk update (the DB method is per-id, MCP layer loops)."""

    def test_single_update(self, db):
        db.update_conversation("c1", starred=True)
        conv = db.load_conversation("c1")
        assert conv.starred_at is not None

    def test_update_returns_state(self, db):
        db.update_conversation("c1", title="New Title")
        conv = db.load_conversation("c1")
        meta = _conv_metadata(conv, db)
        assert meta["title"] == "New Title"
        assert meta["tags"] == ["python"]

    def test_bulk_tags(self, multi_db):
        """Simulate bulk tagging of multiple conversations."""
        for cid in ["c1", "c2", "c3"]:
            multi_db.update_conversation(cid, add_tags=["bulk-tagged"])
        for cid in ["c1", "c2", "c3"]:
            conv = multi_db.load_conversation(cid)
            assert "bulk-tagged" in conv.tags

    def test_update_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_conversation("nonexistent", title="x")

    def test_pin_unpin(self, db):
        db.update_conversation("c1", pinned=True)
        assert db.load_conversation("c1").pinned_at is not None
        db.update_conversation("c1", pinned=False)
        assert db.load_conversation("c1").pinned_at is None

    def test_archive(self, db):
        db.update_conversation("c1", archived=True)
        assert db.load_conversation("c1").archived_at is not None

    def test_sensitive(self, db):
        db.update_conversation("c1", sensitive=True)
        assert db.load_conversation("c1").sensitive is True

    def test_summary(self, db):
        db.update_conversation("c1", summary="A summary")
        assert db.load_conversation("c1").summary == "A summary"

    def test_metadata_merge(self, db):
        db.update_conversation("c1", metadata={"key": "value"})
        conv = db.load_conversation("c1")
        assert conv.metadata["key"] == "value"


class TestAppendMessage:
    def test_append(self, db):
        db.append_message(
            "c1",
            Message(id="m3", role="user", content=[text_block("more")], parent_id="m2"),
        )
        conv = db.load_conversation("c1")
        assert conv.message_count == 3

    def test_append_returns_updated_state(self, db):
        """After append, we should be able to get updated conversation metadata."""
        db.append_message(
            "c1",
            Message(id="m3", role="user", content=[text_block("more")], parent_id="m2"),
        )
        conv = db.load_conversation("c1")
        meta = _conv_metadata(conv, db)
        assert meta["message_count"] == 3

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
        assert "CREATE TABLE messages" in schema
        assert "messages_fts" in schema

    def test_statistics(self, db):
        stats = db.get_statistics()
        assert stats["total_conversations"] == 1
        assert stats["total_messages"] == 2
        assert "openai" in stats["sources"]
        assert "python" in stats["tags"]


class TestConvMetadata:
    """Test the _conv_metadata helper used by all tools."""

    def test_fields(self, db):
        conv = db.load_conversation("c1")
        meta = _conv_metadata(conv, db)
        assert "id" in meta
        assert "title" in meta
        assert "tags" in meta
        assert "starred" in meta
        assert "pinned" in meta
        assert "archived" in meta
        assert isinstance(meta["starred"], bool)
        assert isinstance(meta["pinned"], bool)
        assert isinstance(meta["archived"], bool)

    def test_tags_list(self, db):
        conv = db.load_conversation("c1")
        meta = _conv_metadata(conv, db)
        assert meta["tags"] == ["python"]

    def test_boolean_flags_default_false(self, db):
        conv = db.load_conversation("c1")
        meta = _conv_metadata(conv, db)
        assert meta["starred"] is False
        assert meta["pinned"] is False
        assert meta["archived"] is False


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
