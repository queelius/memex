from llm_memex.models import text_block, media_block, tool_use_block, tool_result_block, thinking_block

class TestContentBlocks:
    def test_text_block(self):
        assert text_block("hello") == {"type": "text", "text": "hello"}

    def test_media_block_url(self):
        b = media_block("image/png", url="https://example.com/img.png")
        assert b == {"type": "media", "media_type": "image/png", "url": "https://example.com/img.png"}

    def test_media_block_data(self):
        b = media_block("image/jpeg", data="base64data==")
        assert b == {"type": "media", "media_type": "image/jpeg", "data": "base64data=="}

    def test_media_block_filename(self):
        assert media_block("application/pdf", url="x", filename="doc.pdf")["filename"] == "doc.pdf"

    def test_media_block_minimal(self):
        assert media_block("audio/mp3") == {"type": "media", "media_type": "audio/mp3"}

    def test_tool_use_block(self):
        b = tool_use_block("call_1", "search", {"query": "test"})
        assert b == {"type": "tool_use", "id": "call_1", "name": "search", "input": {"query": "test"}}

    def test_tool_result_block(self):
        assert tool_result_block("call_1", content="5 results") == {
            "type": "tool_result", "tool_use_id": "call_1", "content": "5 results"
        }

    def test_tool_result_error(self):
        assert tool_result_block("call_1", content="fail", is_error=True)["is_error"] is True

    def test_tool_result_minimal(self):
        assert tool_result_block("call_1") == {"type": "tool_result", "tool_use_id": "call_1"}

    def test_thinking_block(self):
        assert thinking_block("reasoning...") == {"type": "thinking", "text": "reasoning..."}

from datetime import datetime
from llm_memex.models import Message, Conversation

class TestMessage:
    def test_create_simple(self):
        msg = Message(id="m1", role="user", content=[text_block("hello")])
        assert msg.id == "m1"
        assert msg.parent_id is None
        assert msg.sensitive is False
        assert msg.metadata == {}

    def test_get_text(self):
        msg = Message(id="m1", role="user", content=[text_block("a"), text_block("b")])
        assert msg.get_text() == "a\nb"

    def test_get_text_skips_non_text(self):
        msg = Message(id="m1", role="assistant", content=[
            text_block("before"), tool_use_block("c1", "search", {"q": "x"}), text_block("after"),
        ])
        assert msg.get_text() == "before\nafter"

    def test_get_text_empty(self):
        assert Message(id="m1", role="user", content=[]).get_text() == ""

class TestConversation:
    def _linear(self):
        now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        for i, (role, txt) in enumerate([("user","q1"),("assistant","a1"),("user","q2"),("assistant","a2")], 1):
            conv.add_message(Message(
                id=f"m{i}", role=role, content=[text_block(txt)],
                parent_id=f"m{i-1}" if i > 1 else None,
            ))
        return conv

    def test_add_message(self):
        conv = self._linear()
        assert len(conv.messages) == 4
        assert conv.root_ids == ["m1"]
        assert conv.message_count == 4

    def test_get_children(self):
        conv = self._linear()
        assert [c.id for c in conv.get_children("m1")] == ["m2"]
        assert [c.id for c in conv.get_children(None)] == ["m1"]

    def test_get_all_paths_linear(self):
        paths = self._linear().get_all_paths()
        assert len(paths) == 1
        assert [m.id for m in paths[0]] == ["m1", "m2", "m3", "m4"]

    def test_get_all_paths_branching(self):
        now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        conv.add_message(Message(id="m1", role="user", content=[text_block("q")]))
        conv.add_message(Message(id="m2a", role="assistant", content=[text_block("a1")], parent_id="m1"))
        conv.add_message(Message(id="m2b", role="assistant", content=[text_block("a2")], parent_id="m1"))
        paths = conv.get_all_paths()
        assert len(paths) == 2
        assert {tuple(m.id for m in p) for p in paths} == {("m1","m2a"), ("m1","m2b")}

    def test_get_path(self):
        conv = self._linear()
        assert [m.id for m in conv.get_path("m3")] == ["m1", "m2", "m3"]

    def test_get_path_not_found(self):
        assert self._linear().get_path("nope") is None

    def test_get_leaf_ids(self):
        assert self._linear().get_leaf_ids() == ["m4"]

    def test_get_all_paths_deep_chain(self):
        """Iterative get_all_paths should handle chains > 1000 messages (issue #10)."""
        conv = Conversation(id="deep", created_at=datetime.now(), updated_at=datetime.now())
        # Build a chain of 1500 messages (exceeds Python default recursion limit of 1000)
        for i in range(1500):
            conv.add_message(Message(
                id=f"m{i}", role="user", content=[text_block(f"msg{i}")],
                parent_id=f"m{i-1}" if i > 0 else None,
            ))
        paths = conv.get_all_paths()
        assert len(paths) == 1
        assert len(paths[0]) == 1500
        assert paths[0][0].id == "m0"
        assert paths[0][-1].id == "m1499"
