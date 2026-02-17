from memex.models import text_block, media_block, tool_use_block, tool_result_block, thinking_block

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
