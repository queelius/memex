"""Tests for memex importers: OpenAI, Anthropic, Gemini."""
import json

from memex.importers.openai import detect as openai_detect
from memex.importers.openai import import_file as openai_import
from memex.importers.anthropic import detect as anthropic_detect
from memex.importers.anthropic import import_file as anthropic_import
from memex.importers.gemini import detect as gemini_detect
from memex.importers.gemini import import_file as gemini_import


# ---------- OpenAI ----------

class TestOpenAIDetect:
    def test_valid_file(self, tmp_path):
        f = tmp_path / "export.json"
        f.write_text(json.dumps([{
            "id": "conv1",
            "mapping": {"node1": {"message": {"content": {"parts": ["hi"]}}}},
        }]))
        assert openai_detect(str(f)) is True

    def test_invalid_format(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text(json.dumps({"not": "openai"}))
        assert openai_detect(str(f)) is False

    def test_nonexistent_file(self, tmp_path):
        assert openai_detect(str(tmp_path / "nope.json")) is False

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all")
        assert openai_detect(str(f)) is False

    def test_empty_list(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("[]")
        assert openai_detect(str(f)) is False


class TestOpenAIImport:
    def test_simple_conversation(self, tmp_path):
        data = [{
            "id": "conv1", "title": "Test Chat",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "root": {"id": "root", "children": ["m1"], "message": None},
                "m1": {
                    "id": "m1", "parent": "root", "children": ["m2"],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
                "m2": {
                    "id": "m2", "parent": "m1", "children": [],
                    "message": {
                        "id": "m2", "author": {"role": "assistant"},
                        "content": {"parts": ["hi there"]},
                        "create_time": 1700000001,
                        "metadata": {"model_slug": "gpt-4"},
                    },
                },
            },
        }]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = openai_import(str(f))
        assert len(convs) == 1
        conv = convs[0]
        assert conv.title == "Test Chat"
        assert conv.source == "openai"
        assert conv.model == "gpt-4"
        assert len(conv.messages) == 2

    def test_multimodal_content(self, tmp_path):
        data = [{
            "id": "conv2", "title": "Image Chat",
            "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {
                            "parts": [
                                "look at this",
                                {"asset_pointer": "file://img.png"},
                            ],
                        },
                        "create_time": 1700000000,
                    },
                },
            },
        }]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = openai_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "media"
        assert msg.content[1]["url"] == "file://img.png"

    def test_skips_empty_system_messages(self, tmp_path):
        data = [{
            "id": "conv3", "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "sys": {
                    "id": "sys", "parent": None, "children": ["m1"],
                    "message": {
                        "id": "sys", "author": {"role": "system"},
                        "content": {"parts": []},
                        "create_time": 1700000000,
                    },
                },
                "m1": {
                    "id": "m1", "parent": "sys", "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                        "create_time": 1700000000,
                    },
                },
            },
        }]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = openai_import(str(f))
        # System message skipped, only user message
        assert len(convs[0].messages) == 1

    def test_empty_mapping(self, tmp_path):
        data = [{"id": "conv4", "mapping": {}}]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = openai_import(str(f))
        assert len(convs) == 0

    def test_tool_use_content(self, tmp_path):
        data = [{
            "id": "conv5", "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "m1": {
                    "id": "m1", "parent": None, "children": [],
                    "message": {
                        "id": "m1", "author": {"role": "assistant"},
                        "content": {
                            "parts": [
                                {"type": "tool_use", "id": "tu1", "name": "search", "input": {"q": "test"}},
                            ],
                        },
                        "create_time": 1700000000,
                    },
                },
            },
        }]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = openai_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert msg.content[0]["type"] == "tool_use"
        assert msg.content[0]["name"] == "search"


# ---------- Anthropic ----------

class TestAnthropicDetect:
    def test_chat_messages_format(self, tmp_path):
        f = tmp_path / "claude.json"
        f.write_text(json.dumps([{
            "uuid": "abc", "name": "My Chat",
            "chat_messages": [{"sender": "human", "text": "hi"}],
        }]))
        assert anthropic_detect(str(f)) is True

    def test_uuid_name_format(self, tmp_path):
        f = tmp_path / "claude.json"
        f.write_text(json.dumps([{"uuid": "abc", "name": "Chat"}]))
        assert anthropic_detect(str(f)) is True

    def test_invalid_format(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text(json.dumps({"some": "data"}))
        assert anthropic_detect(str(f)) is False

    def test_nonexistent_file(self, tmp_path):
        assert anthropic_detect(str(tmp_path / "nope.json")) is False


class TestAnthropicImport:
    def test_chat_messages_format(self, tmp_path):
        data = [{
            "uuid": "conv1", "name": "Test Chat",
            "created_at": "2024-01-01T00:00:00Z",
            "chat_messages": [
                {"uuid": "m1", "sender": "human", "text": "hello"},
                {"uuid": "m2", "sender": "assistant", "text": "hi back"},
            ],
        }]
        f = tmp_path / "claude.json"
        f.write_text(json.dumps(data))
        convs = anthropic_import(str(f))
        assert len(convs) == 1
        conv = convs[0]
        assert conv.title == "Test Chat"
        assert conv.source == "anthropic"
        assert len(conv.messages) == 2
        msgs = list(conv.messages.values())
        assert msgs[0].role == "user"
        assert msgs[0].get_text() == "hello"
        assert msgs[1].role == "assistant"

    def test_multipart_content(self, tmp_path):
        data = [{
            "uuid": "conv2", "name": "Multi",
            "chat_messages": [{
                "uuid": "m1", "sender": "assistant",
                "content": [
                    {"type": "text", "text": "here's the code"},
                    {"type": "tool_use", "id": "tu1", "name": "edit", "input": {"file": "a.py"}},
                ],
            }],
        }]
        f = tmp_path / "claude.json"
        f.write_text(json.dumps(data))
        convs = anthropic_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "tool_use"

    def test_attachments(self, tmp_path):
        data = [{
            "uuid": "conv3", "name": "Attach",
            "chat_messages": [{
                "uuid": "m1", "sender": "human",
                "text": "see attached",
                "attachments": [{"file_name": "report.pdf", "file_type": "application/pdf"}],
            }],
        }]
        f = tmp_path / "claude.json"
        f.write_text(json.dumps(data))
        convs = anthropic_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "media"
        assert msg.content[1]["filename"] == "report.pdf"

    def test_tags_default(self, tmp_path):
        data = [{"uuid": "conv4", "name": "Tags", "chat_messages": []}]
        f = tmp_path / "claude.json"
        f.write_text(json.dumps(data))
        convs = anthropic_import(str(f))
        assert "anthropic" in convs[0].tags
        assert "claude" in convs[0].tags


# ---------- Gemini ----------

class TestGeminiDetect:
    def test_conversations_key(self, tmp_path):
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps({"conversations": [{"id": "c1"}]}))
        assert gemini_detect(str(f)) is True

    def test_turns_key(self, tmp_path):
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps({"turns": [{"role": "user"}]}))
        assert gemini_detect(str(f)) is True

    def test_conversation_id_key(self, tmp_path):
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps({"conversation_id": "abc"}))
        assert gemini_detect(str(f)) is True

    def test_list_with_gemini_marker(self, tmp_path):
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps([{"model": "gemini-1.5-pro", "turns": []}]))
        assert gemini_detect(str(f)) is True

    def test_invalid_format(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text(json.dumps({"some": "data"}))
        assert gemini_detect(str(f)) is False

    def test_nonexistent_file(self, tmp_path):
        assert gemini_detect(str(tmp_path / "nope.json")) is False


class TestGeminiImport:
    def test_turns_format(self, tmp_path):
        data = {
            "conversations": [{
                "id": "conv1", "title": "Gemini Chat",
                "created_at": 1700000000,
                "turns": [
                    {"id": "m1", "role": "user", "parts": [{"text": "hello"}]},
                    {"id": "m2", "role": "model", "parts": [{"text": "hi!"}]},
                ],
            }],
        }
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        assert len(convs) == 1
        conv = convs[0]
        assert conv.title == "Gemini Chat"
        assert conv.source == "gemini"
        assert len(conv.messages) == 2
        msgs = list(conv.messages.values())
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"  # "model" mapped to "assistant"

    def test_inline_data(self, tmp_path):
        data = {
            "conversations": [{
                "id": "conv2", "title": "Image",
                "turns": [{
                    "id": "m1", "role": "user",
                    "parts": [
                        {"text": "what's this?"},
                        {"inline_data": {"mime_type": "image/jpeg", "data": "base64data"}},
                    ],
                }],
            }],
        }
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "media"
        assert msg.content[1]["data"] == "base64data"

    def test_simple_text_content(self, tmp_path):
        data = {
            "conversations": [{
                "id": "conv3", "title": "Simple",
                "turns": [{"id": "m1", "role": "user", "content": "plain text"}],
            }],
        }
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert msg.get_text() == "plain text"

    def test_string_parts(self, tmp_path):
        data = {
            "conversations": [{
                "id": "conv4", "title": "Strings",
                "turns": [{"id": "m1", "role": "user", "parts": ["hello", "world"]}],
            }],
        }
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        msg = list(convs[0].messages.values())[0]
        assert len(msg.content) == 2
        assert msg.content[0]["text"] == "hello"
        assert msg.content[1]["text"] == "world"

    def test_tags_default(self, tmp_path):
        data = {"conversations": [{"id": "c1", "title": "T", "turns": []}]}
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        assert "google" in convs[0].tags
        assert "gemini" in convs[0].tags

    def test_model_detection(self, tmp_path):
        data = {
            "conversations": [{
                "id": "c1", "title": "T", "model": "gemini-1.5-pro",
                "turns": [],
            }],
        }
        f = tmp_path / "gemini.json"
        f.write_text(json.dumps(data))
        convs = gemini_import(str(f))
        assert convs[0].model == "gemini-1.5-pro"
