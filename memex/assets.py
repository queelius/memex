"""Asset management for media blocks — resolution, copying, and rendering."""
from __future__ import annotations

import base64
import hashlib
import glob
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memex.models import Conversation


# ── Media type helpers ──────────────────────────────────────────

_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "application/pdf": ".pdf",
}


def _media_type_to_ext(media_type: str) -> str:
    """Map a MIME type to a file extension."""
    if media_type in _EXT_MAP:
        return _EXT_MAP[media_type]
    # Fallback: use subtype (e.g. "image/tiff" -> ".tiff")
    parts = media_type.split("/")
    if len(parts) == 2:
        return f".{parts[1]}"
    return ".bin"


def _safe_filename(name: str | None, msg_id: str, index: int, media_type: str) -> str:
    """Generate a safe, unique filename for an asset."""
    ext = _media_type_to_ext(media_type)
    if name:
        # Sanitize: keep alphanums, hyphens, underscores, dots
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
        # Ensure correct extension
        if not safe.lower().endswith(ext):
            safe = safe + ext
        return safe
    # No name — generate from message ID and block index
    short_id = msg_id[:8] if len(msg_id) >= 8 else msg_id
    return f"{short_id}_{index}{ext}"


def _collision_rename(filepath: Path) -> Path:
    """Append short hash to filename if it already exists."""
    if not filepath.exists():
        return filepath
    # Hash the stem + a counter to create unique name
    stem = filepath.stem
    ext = filepath.suffix
    for i in range(1, 1000):
        h = hashlib.md5(f"{stem}_{i}".encode()).hexdigest()[:6]
        candidate = filepath.parent / f"{stem}_{h}{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique name for {filepath}")


# ── OpenAI asset resolution ────────────────────────────────────

def resolve_openai_assets(conv: Conversation, source_dir: Path) -> int:
    """Resolve file-service:// URLs to local file paths.

    OpenAI exports include files alongside conversations.json. Asset pointers
    use the format file-service://file-{ID}. We glob the source directory
    for matching files and update the URL to the absolute path.
    """
    count = 0
    for msg in conv.messages.values():
        for block in msg.content:
            if block.get("type") != "media":
                continue
            url = block.get("url", "")
            if not url.startswith("file-service://file-"):
                continue
            file_id = url.replace("file-service://", "")
            # Search common locations
            patterns = [
                str(source_dir / f"{file_id}-*"),
                str(source_dir / "dalle-generations" / f"{file_id}-*"),
            ]
            for pattern in patterns:
                matches = glob.glob(pattern)
                if matches:
                    block["url"] = str(Path(matches[0]).resolve())
                    count += 1
                    break
    return count


# ── Asset copying ──────────────────────────────────────────────

def copy_assets(conv: Conversation, asset_dir: Path) -> int:
    """Copy referenced assets into asset_dir, rewriting URLs to relative paths.

    Handles three cases:
    1. Absolute file path → copy file, set url to assets/{filename}
    2. Base64 data (no usable url) → decode, write, set url, delete data key
    3. Already relative assets/ URL → skip (idempotent)
    """
    asset_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for msg in conv.messages.values():
        for i, block in enumerate(msg.content):
            if block.get("type") != "media":
                continue
            url = block.get("url", "")
            media_type = block.get("media_type", "application/octet-stream")

            # Already a relative assets/ path — skip
            if url.startswith("assets/"):
                continue

            # Case 1: absolute file path
            if url and Path(url).is_absolute() and Path(url).is_file():
                src = Path(url)
                filename = _safe_filename(
                    block.get("filename") or src.name, msg.id, i, media_type
                )
                dest = _collision_rename(asset_dir / filename)
                shutil.copy2(str(src), str(dest))
                block["url"] = f"assets/{dest.name}"
                count += 1
                continue

            # Case 2: base64 data with no usable file URL
            data = block.get("data")
            if data:
                filename = _safe_filename(
                    block.get("filename"), msg.id, i, media_type
                )
                dest = _collision_rename(asset_dir / filename)
                dest.write_bytes(base64.b64decode(data))
                block["url"] = f"assets/{dest.name}"
                del block["data"]
                count += 1
                continue
    return count


# ── Source-type dispatcher ─────────────────────────────────────

def resolve_source_assets(conv: Conversation, source_dir: Path, source_type: str) -> int:
    """Resolve source-specific asset references before copying.

    Only OpenAI needs resolution (file-service:// URLs).
    Anthropic/Gemini use base64 inline — handled directly by copy_assets.
    """
    if source_type == "openai":
        return resolve_openai_assets(conv, source_dir)
    return 0
