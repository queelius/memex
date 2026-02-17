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
        from memex.importers.openai import import_file
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
