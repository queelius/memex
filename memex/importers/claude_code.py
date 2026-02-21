"""Import Claude Code conversation transcripts (JSONL session files).

Claude Code stores sessions as JSONL at ~/.claude/projects/<path>/<uuid>.jsonl.
Each line is a JSON event (user, assistant, progress, file-history-snapshot, etc.).

This importer captures the **conversation skeleton** only: real user requests and
assistant text responses. Tool use, thinking blocks, progress events, and file
snapshots are stripped. Metadata records the mode as "conversation_only" so a
future full-fidelity importer (claude_code_full) can coexist.
"""
import json
from datetime import datetime, timezone
from typing import List

from memex.models import Conversation, Message, text_block

# Event types that Claude Code uses (for detection)
_KNOWN_EVENT_TYPES = {
    "user", "assistant", "system", "progress",
    "file-history-snapshot", "queue-operation",
}


def detect(path: str) -> bool:
    """Check if file is a Claude Code JSONL session transcript."""
    try:
        if not path.endswith(".jsonl"):
            return False
        with open(path) as f:
            first_line = f.readline()
        record = json.loads(first_line)
        return (
            "sessionId" in record or "type" in record
        ) and record.get("type") in _KNOWN_EVENT_TYPES
    except (json.JSONDecodeError, IOError, KeyError, IndexError):
        return False


def _parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp, handling trailing Z."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def import_file(path: str) -> List[Conversation]:
    """Import a Claude Code JSONL session as a single conversation.

    Extracts only the conversation skeleton:
    - User messages: type="user", userType="external", not sidechain, plain text
    - Assistant messages: type="assistant", not sidechain, text blocks only
    """
    with open(path) as f:
        records = [json.loads(line) for line in f if line.strip()]

    if not records:
        return []

    # Extract session metadata from first record with sessionId
    session_id = None
    slug = None
    first_ts = None
    last_ts = None
    model = None

    for rec in records:
        if session_id is None and rec.get("sessionId"):
            session_id = rec["sessionId"]
        if slug is None and rec.get("slug"):
            slug = rec["slug"]
        if rec.get("timestamp"):
            ts = rec["timestamp"]
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        # Extract model from first assistant message
        if model is None and rec.get("type") == "assistant":
            model = rec.get("message", {}).get("model")

    if session_id is None:
        return []

    # Filter to conversation turns
    messages = []
    parent_id = None

    for rec in records:
        event_type = rec.get("type")

        # Skip sidechain messages
        if rec.get("isSidechain"):
            continue

        msg = rec.get("message", {})

        if event_type == "user" and rec.get("userType") == "external":
            content = msg.get("content")
            # Only import plain text user messages (not tool_result arrays)
            if isinstance(content, str) and content.strip():
                msg_id = rec.get("uuid", f"user_{len(messages)}")
                messages.append(Message(
                    id=msg_id,
                    role="user",
                    content=[text_block(content)],
                    parent_id=parent_id,
                    created_at=_parse_iso(rec["timestamp"]) if rec.get("timestamp") else None,
                ))
                parent_id = msg_id

        elif event_type == "assistant":
            content_blocks = msg.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            # Extract only text blocks
            texts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        texts.append(text)
            # Skip assistant turns with no text (pure tool_use)
            if not texts:
                continue
            joined = "\n\n".join(texts)
            msg_id = rec.get("uuid", f"asst_{len(messages)}")
            messages.append(Message(
                id=msg_id,
                role="assistant",
                content=[text_block(joined)],
                parent_id=parent_id,
                model=msg.get("model"),
                created_at=_parse_iso(rec["timestamp"]) if rec.get("timestamp") else None,
            ))
            parent_id = msg_id

    # If no actual messages were extracted, don't create a conversation
    if not messages:
        return []

    # Build title from slug
    title = _slug_to_title(slug) if slug else "Untitled Session"

    now = datetime.now(timezone.utc)
    conv = Conversation(
        id=session_id,
        title=title,
        source="claude_code",
        model=model,
        created_at=_parse_iso(first_ts) if first_ts else now,
        updated_at=_parse_iso(last_ts) if last_ts else now,
        tags=["claude-code"],
    )

    for msg in messages:
        conv.add_message(msg)

    conv.metadata["_provenance"] = {
        "source_type": "claude_code",
        "source_file": path,
        "source_id": session_id,
    }
    conv.metadata["importer_mode"] = "conversation_only"

    return [conv]


def _slug_to_title(slug: str) -> str:
    """Convert a slug like 'immutable-splashing-thompson' to title case."""
    return slug.replace("-", " ").title()
