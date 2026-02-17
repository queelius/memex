from datetime import datetime

from memex.db import Database
from memex.models import (
    Conversation,
    Message,
    text_block,
    tool_result_block,
    tool_use_block,
)


def _make_conv(id="c1", title="Test"):
    now = datetime.now()
    conv = Conversation(
        id=id, created_at=now, updated_at=now, title=title,
        source="test", model="gpt-4", tags=["python", "testing"],
    )
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(
        Message(
            id="m2", role="assistant", content=[text_block("hi")],
            parent_id="m1", model="gpt-4",
        )
    )
    return conv


class TestDatabaseSchema:
    def test_creates_tables(self, tmp_db_path):
        db = Database(tmp_db_path)
        tables = db.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = [r["name"] for r in tables]
        assert "conversations" in names
        assert "messages" in names
        assert "tags" in names
        assert "messages_fts" in names

    def test_creates_indexes(self, tmp_db_path):
        db = Database(tmp_db_path)
        indexes = db.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        names = [r["name"] for r in indexes]
        assert "idx_conversations_created" in names
        assert "idx_messages_parent" in names
        assert "idx_tags_tag" in names

    def test_wal_mode(self, tmp_db_path):
        db = Database(tmp_db_path)
        assert db.execute_sql("PRAGMA journal_mode")[0]["journal_mode"] == "wal"

    def test_foreign_keys(self, tmp_db_path):
        db = Database(tmp_db_path)
        assert db.execute_sql("PRAGMA foreign_keys")[0]["foreign_keys"] == 1

    def test_close_idempotent(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.close()
        db.close()  # no error

    def test_get_schema(self, tmp_db_path):
        db = Database(tmp_db_path)
        schema = db.get_schema()
        assert "CREATE TABLE conversations" in schema
        assert "CREATE TABLE messages" in schema

    def test_memory_db(self):
        db = Database(":memory:")
        tables = db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(tables) >= 3
        db.close()

    def test_execute_sql_returns_dicts(self, tmp_db_path):
        db = Database(tmp_db_path)
        rows = db.execute_sql("SELECT 1 as a, 2 as b")
        assert rows == [{"a": 1, "b": 2}]


class TestSaveLoad:
    def test_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        loaded = db.load_conversation("c1")
        assert loaded.title == "Test"
        assert loaded.source == "test"
        assert loaded.message_count == 2
        assert set(loaded.tags) == {"python", "testing"}

    def test_messages_preserved(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        loaded = db.load_conversation("c1")
        assert loaded.messages["m1"].get_text() == "hello"
        assert loaded.messages["m2"].parent_id == "m1"

    def test_tree_structure(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        paths = db.load_conversation("c1").get_all_paths()
        assert [m.id for m in paths[0]] == ["m1", "m2"]

    def test_load_nonexistent(self, tmp_db_path):
        assert Database(tmp_db_path).load_conversation("nope") is None

    def test_save_overwrites(self, tmp_db_path):
        db = Database(tmp_db_path)
        conv = _make_conv()
        db.save_conversation(conv)
        conv.title = "Updated"
        db.save_conversation(conv)
        assert db.load_conversation("c1").title == "Updated"

    def test_metadata_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path)
        conv = _make_conv()
        conv.metadata = {"q": 0.9}
        db.save_conversation(conv)
        assert db.load_conversation("c1").metadata == {"q": 0.9}

    def test_sensitive_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path)
        conv = _make_conv()
        conv.sensitive = True
        db.save_conversation(conv)
        assert db.load_conversation("c1").sensitive is True

    def test_content_blocks_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path)
        now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        conv.add_message(
            Message(
                id="m1", role="assistant",
                content=[
                    text_block("searching"),
                    tool_use_block("c1", "search", {"q": "test"}),
                ],
            )
        )
        conv.add_message(
            Message(
                id="m2", role="tool",
                content=[tool_result_block("c1", content="found 5")],
                parent_id="m1",
            )
        )
        db.save_conversation(conv)
        m1 = db.load_conversation("c1").messages["m1"]
        assert m1.content[1]["type"] == "tool_use"
        assert m1.content[1]["name"] == "search"


def _populate_db(db):
    for i in range(1, 6):
        now = datetime(2024, 1, i)
        conv = Conversation(
            id=f"c{i}", created_at=now, updated_at=now, title=f"Chat {i}",
            source="openai" if i <= 3 else "anthropic",
            model="gpt-4" if i <= 3 else "claude-3",
            tags=["python"] if i % 2 == 0 else ["rust"],
        )
        if i == 1:
            conv.starred_at = now
        if i == 2:
            conv.pinned_at = now
        if i == 3:
            conv.archived_at = now
        conv.add_message(
            Message(id="m1", role="user", content=[text_block(f"topic {i}")])
        )
        conv.add_message(
            Message(
                id="m2", role="assistant",
                content=[text_block(f"answer {i}")], parent_id="m1",
            )
        )
        db.save_conversation(conv)


class TestQuery:
    def test_all(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        assert len(db.query_conversations()["items"]) == 5

    def test_limit(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        r = db.query_conversations(limit=2)
        assert len(r["items"]) == 2 and r["has_more"] is True

    def test_starred(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        r = db.query_conversations(starred=True)
        assert len(r["items"]) == 1 and r["items"][0]["id"] == "c1"

    def test_source(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        assert len(db.query_conversations(source="anthropic")["items"]) == 2

    def test_tag(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        assert len(db.query_conversations(tag="python")["items"]) == 2

    def test_not_archived(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        assert len(db.query_conversations(archived=False)["items"]) == 4


class TestSearch:
    def test_fts(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        r = db.query_conversations(query="topic 3")
        assert "c3" in [i["id"] for i in r["items"]]

    def test_no_results(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        assert len(db.query_conversations(query="nonexistent_xyz")["items"]) == 0

    def test_with_filter(self, tmp_db_path):
        db = Database(tmp_db_path)
        _populate_db(db)
        r = db.query_conversations(query="topic", source="anthropic")
        for item in r["items"]:
            assert item["id"] in ("c4", "c5")


import pytest


class TestUpdate:
    def test_title(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.update_conversation("c1", title="New")
        assert db.load_conversation("c1").title == "New"

    def test_star_unstar(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.update_conversation("c1", starred=True)
        assert db.load_conversation("c1").starred_at is not None
        db.update_conversation("c1", starred=False)
        assert db.load_conversation("c1").starred_at is None

    def test_add_remove_tags(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.update_conversation("c1", add_tags=["new"])
        assert "new" in db.load_conversation("c1").tags
        db.update_conversation("c1", remove_tags=["python"])
        assert "python" not in db.load_conversation("c1").tags

    def test_metadata_merge(self, tmp_db_path):
        db = Database(tmp_db_path)
        conv = _make_conv()
        conv.metadata = {"a": 1}
        db.save_conversation(conv)
        db.update_conversation("c1", metadata={"b": 2})
        assert db.load_conversation("c1").metadata == {"a": 1, "b": 2}

    def test_summary(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.update_conversation("c1", summary="A test.")
        assert db.load_conversation("c1").summary == "A test."

    def test_nonexistent(self, tmp_db_path):
        with pytest.raises(ValueError, match="not found"):
            Database(tmp_db_path).update_conversation("nope", title="x")


class TestAppend:
    def test_append(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.append_message(
            "c1",
            Message(
                id="m3", role="user",
                content=[text_block("followup")], parent_id="m2",
            ),
        )
        loaded = db.load_conversation("c1")
        assert len(loaded.messages) == 3 and loaded.message_count == 3

    def test_branch(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.append_message(
            "c1",
            Message(
                id="m2b", role="assistant",
                content=[text_block("alt")], parent_id="m1",
            ),
        )
        assert len(db.load_conversation("c1").get_all_paths()) == 2

    def test_nonexistent(self, tmp_db_path):
        with pytest.raises(ValueError, match="not found"):
            Database(tmp_db_path).append_message(
                "nope",
                Message(id="m1", role="user", content=[text_block("x")]),
            )

    def test_updates_fts(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.save_conversation(_make_conv())
        db.append_message(
            "c1",
            Message(
                id="m3", role="user",
                content=[text_block("unique_xyz_term")], parent_id="m2",
            ),
        )
        assert len(db.query_conversations(query="unique_xyz_term")["items"]) == 1
