"""Tests for media rendering, asset resolution, and asset copying."""
import base64
from datetime import datetime
from pathlib import Path

from memex.assets import (
    copy_assets,
    resolve_openai_assets,
    resolve_source_assets,
    _media_type_to_ext,
    _safe_filename,
)
from memex.models import (
    Conversation,
    Message,
    _render_media_md,
    media_block,
    text_block,
    tool_use_block,
)


# ── _render_media_md ────────────────────────────────────────────

class TestRenderMediaMd:
    def test_image_with_url(self):
        block = media_block("image/png", url="https://example.com/photo.png")
        assert _render_media_md(block) == "![image](https://example.com/photo.png)"

    def test_image_with_filename(self):
        block = media_block("image/jpeg", url="assets/pic.jpg", filename="sunset.jpg")
        assert _render_media_md(block) == "![sunset.jpg](assets/pic.jpg)"

    def test_audio(self):
        block = media_block("audio/mpeg", url="assets/song.mp3", filename="song.mp3")
        assert _render_media_md(block) == "[audio: song.mp3](assets/song.mp3)"

    def test_video(self):
        block = media_block("video/mp4", url="assets/clip.mp4", filename="clip.mp4")
        assert _render_media_md(block) == "[video: clip.mp4](assets/clip.mp4)"

    def test_pdf(self):
        block = media_block("application/pdf", url="assets/doc.pdf", filename="doc.pdf")
        assert _render_media_md(block) == "[pdf: doc.pdf](assets/doc.pdf)"

    def test_base64_image_data_uri(self):
        data = base64.b64encode(b"fake-png-data").decode()
        block = media_block("image/png", data=data)
        result = _render_media_md(block)
        assert result.startswith("![image](data:image/png;base64,")
        assert data in result

    def test_no_url_no_data_with_filename(self):
        block = {"type": "media", "media_type": "image/png", "filename": "lost.png"}
        assert _render_media_md(block) == "[lost.png]"

    def test_no_url_no_data_no_filename(self):
        block = {"type": "media", "media_type": "image/png"}
        assert _render_media_md(block) == ""

    def test_unknown_type_fallback(self):
        block = media_block("application/zip", url="assets/archive.zip", filename="archive.zip")
        assert _render_media_md(block) == "[attachment: archive.zip](assets/archive.zip)"


# ── Message.get_content_md ──────────────────────────────────────

class TestGetContentMd:
    def test_mixed_text_and_image(self):
        msg = Message(
            id="m1", role="assistant",
            content=[
                text_block("Here is the image:"),
                media_block("image/png", url="assets/photo.png"),
            ],
        )
        result = msg.get_content_md()
        assert "Here is the image:" in result
        assert "![image](assets/photo.png)" in result
        # Paragraph spacing between blocks
        assert "\n\n" in result

    def test_skips_tool_use(self):
        msg = Message(
            id="m1", role="assistant",
            content=[
                text_block("Calling a tool"),
                tool_use_block("t1", "search", {"q": "test"}),
                text_block("Got results"),
            ],
        )
        result = msg.get_content_md()
        assert "Calling a tool" in result
        assert "Got results" in result
        assert "search" not in result

    def test_text_only_matches_get_text(self):
        msg = Message(
            id="m1", role="user",
            content=[text_block("Hello"), text_block("World")],
        )
        # get_content_md uses \n\n, get_text uses \n
        assert msg.get_content_md() == "Hello\n\nWorld"
        assert msg.get_text() == "Hello\nWorld"

    def test_empty_content(self):
        msg = Message(id="m1", role="user", content=[])
        assert msg.get_content_md() == ""


# ── Helpers ─────────────────────────────────────────────────────

class TestHelpers:
    def test_media_type_to_ext_known(self):
        assert _media_type_to_ext("image/png") == ".png"
        assert _media_type_to_ext("audio/mpeg") == ".mp3"
        assert _media_type_to_ext("application/pdf") == ".pdf"

    def test_media_type_to_ext_fallback(self):
        assert _media_type_to_ext("image/tiff") == ".tiff"

    def test_safe_filename_with_name(self):
        result = _safe_filename("photo.png", "msg123", 0, "image/png")
        assert result == "photo.png"

    def test_safe_filename_without_name(self):
        result = _safe_filename(None, "abcdefghij", 2, "image/jpeg")
        assert result == "abcdefgh_2.jpg"

    def test_safe_filename_sanitizes(self):
        result = _safe_filename("my file (1).png", "msg1", 0, "image/png")
        assert " " not in result
        assert "(" not in result
        assert result.endswith(".png")


# ── resolve_openai_assets ───────────────────────────────────────

class TestResolveOpenaiAssets:
    def test_resolves_file_service_url(self, tmp_path):
        # Create a fake exported file
        fake_file = tmp_path / "file-abc123-photo.png"
        fake_file.write_bytes(b"PNG data")

        conv = _make_conv([
            media_block("image/png", url="file-service://file-abc123"),
        ])
        count = resolve_openai_assets(conv, tmp_path)
        assert count == 1
        block = conv.messages["m1"].content[0]
        assert block["url"] == str(fake_file.resolve())

    def test_resolves_dalle_subdir(self, tmp_path):
        dalle_dir = tmp_path / "dalle-generations"
        dalle_dir.mkdir()
        fake_file = dalle_dir / "file-xyz789-art.png"
        fake_file.write_bytes(b"DALLE data")

        conv = _make_conv([
            media_block("image/png", url="file-service://file-xyz789"),
        ])
        count = resolve_openai_assets(conv, tmp_path)
        assert count == 1
        assert "dalle-generations" in conv.messages["m1"].content[0]["url"]

    def test_unresolvable_leaves_url_unchanged(self, tmp_path):
        conv = _make_conv([
            media_block("image/png", url="file-service://file-missing"),
        ])
        count = resolve_openai_assets(conv, tmp_path)
        assert count == 0
        assert conv.messages["m1"].content[0]["url"] == "file-service://file-missing"

    def test_skips_non_file_service_urls(self, tmp_path):
        conv = _make_conv([
            media_block("image/png", url="https://example.com/img.png"),
        ])
        count = resolve_openai_assets(conv, tmp_path)
        assert count == 0


# ── copy_assets ─────────────────────────────────────────────────

class TestCopyAssets:
    def test_copy_from_absolute_path(self, tmp_path):
        src_file = tmp_path / "source" / "photo.png"
        src_file.parent.mkdir()
        src_file.write_bytes(b"PNG image data")

        asset_dir = tmp_path / "db" / "assets"
        conv = _make_conv([
            media_block("image/png", url=str(src_file)),
        ])
        count = copy_assets(conv, asset_dir)
        assert count == 1
        block = conv.messages["m1"].content[0]
        assert block["url"].startswith("assets/")
        # Verify file was actually copied
        copied = asset_dir / block["url"].removeprefix("assets/")
        assert copied.exists()
        assert copied.read_bytes() == b"PNG image data"

    def test_copy_from_base64(self, tmp_path):
        raw = b"decoded image bytes"
        b64 = base64.b64encode(raw).decode()
        asset_dir = tmp_path / "assets"
        conv = _make_conv([
            media_block("image/png", data=b64),
        ])
        count = copy_assets(conv, asset_dir)
        assert count == 1
        block = conv.messages["m1"].content[0]
        assert block["url"].startswith("assets/")
        assert "data" not in block  # data key removed
        # Verify file written correctly
        written = asset_dir / block["url"].removeprefix("assets/")
        assert written.read_bytes() == raw

    def test_idempotent_skips_relative_urls(self, tmp_path):
        asset_dir = tmp_path / "assets"
        conv = _make_conv([
            media_block("image/png", url="assets/already-there.png"),
        ])
        count = copy_assets(conv, asset_dir)
        assert count == 0
        assert conv.messages["m1"].content[0]["url"] == "assets/already-there.png"

    def test_collision_rename(self, tmp_path):
        asset_dir = tmp_path / "assets"
        asset_dir.mkdir(parents=True)
        # Pre-create a file with the same name
        (asset_dir / "photo.png").write_bytes(b"existing")

        src_file = tmp_path / "photo.png"
        src_file.write_bytes(b"new data")
        conv = _make_conv([
            media_block("image/png", url=str(src_file), filename="photo.png"),
        ])
        count = copy_assets(conv, asset_dir)
        assert count == 1
        # Should have been renamed to avoid collision
        url = conv.messages["m1"].content[0]["url"]
        assert url.startswith("assets/photo_")
        assert url.endswith(".png")

    def test_skips_non_media_blocks(self, tmp_path):
        asset_dir = tmp_path / "assets"
        conv = _make_conv([text_block("just text")])
        count = copy_assets(conv, asset_dir)
        assert count == 0


# ── resolve_source_assets ───────────────────────────────────────

class TestResolveSourceAssets:
    def test_dispatches_openai(self, tmp_path):
        fake_file = tmp_path / "file-test1-img.png"
        fake_file.write_bytes(b"data")
        conv = _make_conv([
            media_block("image/png", url="file-service://file-test1"),
        ])
        count = resolve_source_assets(conv, tmp_path, "openai")
        assert count == 1

    def test_noop_for_anthropic(self, tmp_path):
        conv = _make_conv([
            media_block("image/png", data=base64.b64encode(b"data").decode()),
        ])
        count = resolve_source_assets(conv, tmp_path, "anthropic")
        assert count == 0

    def test_noop_for_unknown(self, tmp_path):
        conv = _make_conv([media_block("image/png", url="http://x.com/a.png")])
        count = resolve_source_assets(conv, tmp_path, "gemini")
        assert count == 0


# ── Test helper ─────────────────────────────────────────────────

def _make_conv(content_blocks):
    """Create a minimal conversation with one message containing given blocks."""
    now = datetime(2024, 1, 1)
    conv = Conversation(id="test-conv", created_at=now, updated_at=now)
    conv.add_message(Message(id="m1", role="user", content=content_blocks))
    return conv
