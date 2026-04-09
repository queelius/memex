"""End-to-end: import → search → update → export roundtrip."""
import json
import os
import tempfile
from datetime import datetime

from memex.db import Database
from memex.models import Conversation, Message, text_block


class TestRoundtrip:
    def test_full_workflow(self, tmp_db_path):
        db = Database(tmp_db_path)

        # 1. Create and save conversations
        for i in range(3):
            now = datetime(2024, 6, i + 1)
            conv = Conversation(
                id=f"conv{i}",
                created_at=now,
                updated_at=now,
                title=f"Python discussion {i}",
                source="openai",
                model="gpt-4",
                tags=["python", "coding"],
            )
            conv.add_message(
                Message(
                    id="m1",
                    role="user",
                    content=[text_block(f"Tell me about Python topic {i}")],
                )
            )
            conv.add_message(
                Message(
                    id="m2",
                    role="assistant",
                    content=[text_block(f"Python topic {i} is fascinating because...")],
                    parent_id="m1",
                )
            )
            db.save_conversation(conv)

        # 2. Search
        result = db.query_conversations(query="Python topic 1")
        assert len(result["items"]) >= 1

        # 3. Update (star + tag + metadata)
        db.update_conversation(
            "conv0",
            starred=True,
            add_tags=["important"],
            metadata={"reviewed_by": "test"},
        )
        conv0 = db.load_conversation("conv0")
        assert conv0.starred_at is not None
        assert "important" in conv0.tags
        assert conv0.metadata["reviewed_by"] == "test"

        # 4. Append message
        db.append_message(
            "conv0",
            Message(
                id="m3",
                role="user",
                content=[text_block("Follow-up question")],
                parent_id="m2",
            ),
        )
        conv0 = db.load_conversation("conv0")
        assert conv0.message_count == 3

        # 5. Path navigation
        paths = db.list_paths("conv0")
        assert len(paths) == 1
        assert paths[0]["message_count"] == 3
        messages = db.get_path_messages("conv0", path_index=0)
        assert len(messages) == 3

        # 6. SQL query
        rows = db.execute_sql(
            "SELECT id, title FROM conversations WHERE starred_at IS NOT NULL"
        )
        assert len(rows) == 1 and rows[0]["id"] == "conv0"

        # 7. Statistics
        stats = db.get_statistics()
        assert stats["total_conversations"] == 3
        assert stats["total_messages"] == 7  # 3*2 + 1 appended

        # 8. Export
        from memex.exporters.markdown import export as md_export
        from memex.exporters.json_export import export as json_export

        with tempfile.TemporaryDirectory() as td:
            md_export([conv0], os.path.join(td, "out.md"))
            json_export([conv0], os.path.join(td, "out.json"))
            assert os.path.exists(os.path.join(td, "out.md"))
            md_content = open(os.path.join(td, "out.md")).read()
            assert "Python discussion 0" in md_content
            data = json.loads(open(os.path.join(td, "out.json")).read())
            assert data[0]["id"] == "conv0"
            assert len(data[0]["messages"]) == 3

        db.close()


class TestImportExportRoundtrip:
    def test_openai_import_then_json_export(self, tmp_path):
        """Import an OpenAI file, save to DB, export as JSON, verify data."""
        from memex.importers.openai import import_path as import_file
        from memex.exporters.json_export import export as json_export

        # Create fake OpenAI export
        openai_data = [{
            "id": "conv-roundtrip",
            "title": "Roundtrip Test",
            "create_time": 1700000000,
            "update_time": 1700000001,
            "mapping": {
                "root": {"id": "root", "children": ["m1"], "message": None},
                "m1": {
                    "id": "m1", "parent": "root", "children": ["m2"],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["What is Python?"]},
                        "create_time": 1700000000,
                    },
                },
                "m2": {
                    "id": "m2", "parent": "m1", "children": [],
                    "message": {
                        "id": "m2", "author": {"role": "assistant"},
                        "content": {"parts": ["Python is a programming language."]},
                        "create_time": 1700000001,
                        "metadata": {"model_slug": "gpt-4"},
                    },
                },
            },
        }]
        input_file = tmp_path / "openai_export.json"
        input_file.write_text(json.dumps(openai_data))

        # Import
        convs = import_file(str(input_file))
        assert len(convs) == 1

        # Save to DB
        db = Database(str(tmp_path / "db"))
        for conv in convs:
            db.save_conversation(conv)

        # Verify searchable
        result = db.query_conversations(query="Python")
        assert len(result["items"]) >= 1

        # Load back
        loaded = db.load_conversation("conv-roundtrip")
        assert loaded is not None
        assert loaded.title == "Roundtrip Test"
        assert loaded.source == "openai"
        assert loaded.model == "gpt-4"

        # Export as JSON
        out_file = tmp_path / "export.json"
        json_export([loaded], str(out_file))
        exported = json.loads(out_file.read_text())
        assert exported[0]["id"] == "conv-roundtrip"
        assert len(exported[0]["messages"]) == 2

        db.close()


class TestDatabaseOperations:
    def test_concurrent_save_load(self, tmp_db_path):
        """Save multiple conversations then load and verify each."""
        db = Database(tmp_db_path)
        ids = []
        for i in range(10):
            now = datetime(2024, 1, i + 1)
            conv = Conversation(
                id=f"batch-{i}", created_at=now, updated_at=now,
                title=f"Batch {i}", source="test",
            )
            conv.add_message(Message(id="m1", role="user", content=[text_block(f"msg {i}")]))
            db.save_conversation(conv)
            ids.append(f"batch-{i}")

        # Verify all loadable
        for cid in ids:
            loaded = db.load_conversation(cid)
            assert loaded is not None
            assert loaded.id == cid

        # Query with pagination
        page1 = db.query_conversations(limit=3)
        assert len(page1["items"]) == 3
        assert page1["has_more"] is True
        page2 = db.query_conversations(limit=3, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 3
        assert page1["items"][0]["id"] != page2["items"][0]["id"]

        db.close()

    def test_update_then_filter(self, tmp_db_path):
        """Star and archive, then filter queries."""
        db = Database(tmp_db_path)
        for i in range(5):
            now = datetime(2024, 1, i + 1)
            conv = Conversation(
                id=f"filter-{i}", created_at=now, updated_at=now,
                title=f"Filter {i}", source="test",
            )
            conv.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
            db.save_conversation(conv)

        # Star two
        db.update_conversation("filter-0", starred=True)
        db.update_conversation("filter-1", starred=True)
        # Archive one
        db.update_conversation("filter-2", archived=True)

        starred = db.query_conversations(starred=True)
        assert len(starred["items"]) == 2

        archived = db.query_conversations(archived=True)
        assert len(archived["items"]) == 1
        assert archived["items"][0]["id"] == "filter-2"

        not_archived = db.query_conversations(archived=False)
        assert len(not_archived["items"]) == 4

        db.close()


class TestClaudeCodeImportRoundtrip:
    """Import Claude Code transcript → save to DB → search → verify FTS."""

    def test_import_search_verify(self, tmp_path):
        import json as _json
        from memex.importers.claude_code import import_path as import_file

        # Build a minimal Claude Code JSONL
        events = [
            {
                "type": "user", "uuid": "u1", "parentUuid": None,
                "sessionId": "int-test-sess", "slug": "integration-test-session",
                "timestamp": "2026-02-18T10:00:00Z",
                "userType": "external", "isSidechain": False,
                "message": {"role": "user", "content": "Explain quicksort algorithm"},
            },
            {
                "type": "assistant", "uuid": "a1", "parentUuid": "u1",
                "sessionId": "int-test-sess", "slug": "integration-test-session",
                "timestamp": "2026-02-18T10:00:01Z",
                "userType": "external", "isSidechain": False,
                "message": {
                    "role": "assistant", "model": "claude-opus-4-6",
                    "content": [{"type": "text",
                                 "text": "Quicksort is a divide-and-conquer sorting algorithm."}],
                },
            },
        ]
        jsonl_file = tmp_path / "session.jsonl"
        jsonl_file.write_text("\n".join(_json.dumps(e) for e in events))

        # Import
        convs = import_file(str(jsonl_file))
        assert len(convs) == 1

        # Save to DB
        db = Database(str(tmp_path / "db"))
        for conv in convs:
            prov = conv.metadata.pop("_provenance", None)
            db.save_conversation(conv)
            if prov:
                db.save_provenance(conv.id, **prov)

        # Verify searchable via FTS
        result = db.query_conversations(query="quicksort")
        assert len(result["items"]) >= 1
        assert result["items"][0]["id"] == "int-test-sess"

        # Verify message-level search
        msg_results = db.search_messages("divide-and-conquer")
        assert len(msg_results) >= 1

        # Load and verify structure
        loaded = db.load_conversation("int-test-sess")
        assert loaded is not None
        assert loaded.title == "Integration Test Session"
        assert loaded.source == "claude_code"
        assert loaded.model == "claude-opus-4-6"
        assert loaded.message_count == 2
        assert "claude-code" in loaded.tags
        assert loaded.metadata.get("importer_mode") == "conversation_only"

        # Verify provenance
        prov = db.get_provenance("int-test-sess")
        assert len(prov) == 1
        assert prov[0]["source_type"] == "claude_code"

        db.close()


class TestMediaRoundtrip:
    """Save conv with media blocks → load → export markdown → verify media rendered."""

    def test_media_roundtrip(self, tmp_path):
        import tempfile
        from memex.models import media_block as mb
        from memex.exporters.markdown import export as md_export

        db = Database(str(tmp_path / "db"))
        now = datetime(2024, 6, 1)
        conv = Conversation(
            id="media-conv", created_at=now, updated_at=now,
            title="Media Test", source="test",
        )
        conv.add_message(Message(
            id="m1", role="user",
            content=[text_block("Look at this image")],
        ))
        conv.add_message(Message(
            id="m2", role="assistant",
            content=[
                text_block("Here is the image:"),
                mb("image/png", url="assets/photo.png", filename="photo.png"),
            ],
            parent_id="m1",
        ))
        db.save_conversation(conv)

        # Load back
        loaded = db.load_conversation("media-conv")
        assert loaded is not None
        assert loaded.message_count == 2

        # Export as markdown
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out.md")
            md_export([loaded], out)
            content = open(out).read()
            assert "![photo.png](assets/photo.png)" in content
            assert "Here is the image:" in content

        db.close()


class TestEnrichmentWorkflow:
    """Full enrichment workflow: create → enrich → query → filter → statistics."""

    def test_full_enrichment_workflow(self, tmp_db_path):
        db = Database(tmp_db_path)

        # 1. Create conversations
        for i in range(3):
            now = datetime(2024, 6, i + 1)
            conv = Conversation(
                id=f"conv{i}", created_at=now, updated_at=now,
                title=f"Discussion {i}", source="openai",
            )
            conv.add_message(
                Message(id="m1", role="user", content=[text_block(f"topic {i}")])
            )
            db.save_conversation(conv)

        # 2. Enrich conversations
        db.save_enrichments("conv0", [
            {"type": "topic", "value": "python", "source": "claude"},
            {"type": "importance", "value": "high", "source": "heuristic", "confidence": 0.9},
            {"type": "summary", "value": "Discussion about Python", "source": "claude"},
        ])
        db.save_enrichments("conv1", [
            {"type": "topic", "value": "rust", "source": "claude"},
            {"type": "importance", "value": "trivial", "source": "heuristic", "confidence": 0.1},
        ])
        db.save_enrichment("conv2", "topic", "python", "claude")

        # 3. Query enrichments
        python_topics = db.query_enrichments(type="topic", value="python")
        assert len(python_topics) == 2
        assert {r["conversation_id"] for r in python_topics} == {"conv0", "conv2"}

        # 4. Filter conversations by enrichment
        high_importance = db.query_conversations(
            enrichment_type="importance", enrichment_value="high",
        )
        assert len(high_importance["items"]) == 1
        assert high_importance["items"][0]["id"] == "conv0"

        # 5. Verify statistics
        stats = db.get_statistics()
        assert stats["enrichment_types"]["topic"] == 3
        assert stats["enrichment_types"]["importance"] == 2
        assert stats["enrichment_types"]["summary"] == 1
        assert stats["provenance_tracked"] == 0  # No provenance saved yet

        db.close()

    def test_provenance_workflow(self, tmp_db_path):
        from memex.mcp import _conv_metadata
        db = Database(tmp_db_path)

        # 1. Create and save a conversation with provenance
        now = datetime(2024, 6, 1)
        conv = Conversation(
            id="conv1", created_at=now, updated_at=now,
            title="Test", source="openai",
        )
        conv.add_message(
            Message(id="m1", role="user", content=[text_block("hello")])
        )
        db.save_conversation(conv)
        db.save_provenance(
            "conv1", source_type="openai",
            source_file="/data/export.json",
            source_id="orig-id-123",
        )

        # 2. Verify provenance
        prov = db.get_provenance("conv1")
        assert len(prov) == 1
        assert prov[0]["source_type"] == "openai"
        assert prov[0]["source_id"] == "orig-id-123"

        # 3. Verify in _conv_metadata
        loaded = db.load_conversation("conv1")
        meta = _conv_metadata(loaded, db)
        assert len(meta["provenance"]) == 1
        assert meta["provenance"][0]["source_type"] == "openai"

        # 4. Verify statistics
        stats = db.get_statistics()
        assert stats["provenance_tracked"] == 1

        db.close()


class TestParentConversation:
    """parent_conversation_id: persistence, FK behavior, and migration."""

    def test_save_and_load_parent_id(self, tmp_db_path):
        """parent_conversation_id saves and loads correctly."""
        db = Database(tmp_db_path)
        now = datetime(2024, 6, 1)

        # Parent conversation
        parent = Conversation(
            id="parent-1", created_at=now, updated_at=now,
            title="Parent Session", source="claude_code",
        )
        parent.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
        db.save_conversation(parent)

        # Child conversation with parent link
        child = Conversation(
            id="child-1", created_at=now, updated_at=now,
            title="Child Agent", source="claude_code",
            parent_conversation_id="parent-1",
        )
        child.add_message(Message(id="m1", role="user", content=[text_block("agent work")]))
        db.save_conversation(child)

        # Load and verify
        loaded = db.load_conversation("child-1")
        assert loaded.parent_conversation_id == "parent-1"

        # Parent has no parent
        loaded_parent = db.load_conversation("parent-1")
        assert loaded_parent.parent_conversation_id is None

        db.close()

    def test_on_delete_set_null(self, tmp_db_path):
        """Deleting parent sets child's parent_conversation_id to NULL."""
        db = Database(tmp_db_path)
        now = datetime(2024, 6, 1)

        parent = Conversation(
            id="parent-del", created_at=now, updated_at=now,
            title="Parent", source="test",
        )
        parent.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
        db.save_conversation(parent)

        child = Conversation(
            id="child-del", created_at=now, updated_at=now,
            title="Child", source="test",
            parent_conversation_id="parent-del",
        )
        child.add_message(Message(id="m1", role="user", content=[text_block("work")]))
        db.save_conversation(child)

        # Delete parent
        db.delete_conversation("parent-del")

        # Child survives, parent_conversation_id becomes NULL
        loaded = db.load_conversation("child-del")
        assert loaded is not None
        assert loaded.parent_conversation_id is None

        db.close()

    def test_parent_in_conv_metadata(self, tmp_db_path):
        """parent_conversation_id appears in MCP _conv_metadata."""
        from memex.mcp import _conv_metadata
        db = Database(tmp_db_path)
        now = datetime(2024, 6, 1)

        parent = Conversation(
            id="p1", created_at=now, updated_at=now,
            title="Parent", source="test",
        )
        parent.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
        db.save_conversation(parent)

        child = Conversation(
            id="c1", created_at=now, updated_at=now,
            title="Child", source="test",
            parent_conversation_id="p1",
        )
        child.add_message(Message(id="m1", role="user", content=[text_block("work")]))
        db.save_conversation(child)

        loaded = db.load_conversation("c1")
        meta = _conv_metadata(loaded, db)
        assert meta["parent_conversation_id"] == "p1"

        loaded_parent = db.load_conversation("p1")
        meta_parent = _conv_metadata(loaded_parent, db)
        assert meta_parent["parent_conversation_id"] is None

        db.close()

    def test_query_children_via_sql(self, tmp_db_path):
        """Can query child conversations via SQL."""
        db = Database(tmp_db_path)
        now = datetime(2024, 6, 1)

        parent = Conversation(
            id="qp1", created_at=now, updated_at=now,
            title="Parent", source="test",
        )
        parent.add_message(Message(id="m1", role="user", content=[text_block("hi")]))
        db.save_conversation(parent)

        for i in range(3):
            child = Conversation(
                id=f"qc{i}", created_at=now, updated_at=now,
                title=f"Child {i}", source="test",
                parent_conversation_id="qp1",
            )
            child.add_message(Message(id="m1", role="user", content=[text_block("work")]))
            db.save_conversation(child)

        rows = db.execute_sql(
            "SELECT id FROM conversations WHERE parent_conversation_id=? ORDER BY id",
            ("qp1",),
        )
        assert len(rows) == 3
        assert [r["id"] for r in rows] == ["qc0", "qc1", "qc2"]

        db.close()

    def test_migration_v2_to_v3(self, tmp_path):
        """Migration from v2 to v3 adds column and index."""
        import sqlite3
        db_dir = tmp_path / "migrate"
        db_dir.mkdir()
        db_path = str(db_dir / "conversations.db")

        # Create a v2 database manually
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        # Minimal v2 schema (no parent_conversation_id)
        conn.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT, source TEXT, model TEXT, summary TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                starred_at DATETIME, pinned_at DATETIME, archived_at DATETIME,
                sensitive BOOLEAN NOT NULL DEFAULT 0,
                metadata JSON NOT NULL DEFAULT '{}'
            );
            CREATE TABLE messages (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                id TEXT NOT NULL, role TEXT NOT NULL, parent_id TEXT, model TEXT,
                created_at DATETIME, sensitive BOOLEAN NOT NULL DEFAULT 0,
                content JSON NOT NULL, metadata JSON NOT NULL DEFAULT '{}',
                PRIMARY KEY (conversation_id, id)
            );
            CREATE TABLE tags (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                tag TEXT NOT NULL, PRIMARY KEY (conversation_id, tag)
            );
            CREATE VIRTUAL TABLE messages_fts USING fts5(
                conversation_id UNINDEXED, message_id UNINDEXED, text,
                tokenize = 'porter unicode61'
            );
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            CREATE TABLE enrichments (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                type TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
                confidence REAL, created_at DATETIME NOT NULL,
                PRIMARY KEY (conversation_id, type, value)
            );
            CREATE TABLE provenance (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL, source_file TEXT, source_id TEXT,
                source_hash TEXT, imported_at DATETIME NOT NULL, importer_version TEXT,
                PRIMARY KEY (conversation_id, source_type)
            );
        """)
        conn.execute("INSERT INTO schema_version (version) VALUES (2)")
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) "
            "VALUES ('test', 'Test', '2024-01-01', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        # Open with Database, should auto-migrate to current SCHEMA_VERSION
        db = Database(str(db_dir))
        # Verify version is at the current SCHEMA_VERSION (chains v2 -> v3 -> ...)
        from memex.db import SCHEMA_VERSION
        row = db.execute_sql("SELECT version FROM schema_version")
        assert row[0]["version"] == SCHEMA_VERSION

        # Verify parent_conversation_id column was added in v3 migration
        conv = db.load_conversation("test")
        assert conv is not None
        assert conv.parent_conversation_id is None

        # Verify index exists
        indexes = db.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_conversations_parent'"
        )
        assert len(indexes) == 1

        db.close()
