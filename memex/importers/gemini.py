"""Import Google Gemini conversation exports."""
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from memex.models import Conversation, Message, media_block, text_block


def detect(path: str) -> bool:
    """Check if file is a Gemini conversation export."""
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            if any(k in data for k in ("conversations", "turns", "conversation_id")):
                return True
        if isinstance(data, list) and data:
            sample = str(data[0]).lower()
            if "gemini" in sample or "bard" in sample:
                return True
        return False
    except (json.JSONDecodeError, IOError, KeyError, IndexError):
        return False


def import_file(path: str) -> List[Conversation]:
    """Import conversations from a Gemini export file."""
    with open(path) as f:
        data = json.load(f)
    # Normalize to list of conversation dicts
    if isinstance(data, dict):
        if "conversations" in data:
            conv_list = data["conversations"]
        else:
            conv_list = [data]
    elif isinstance(data, list):
        conv_list = data
    else:
        conv_list = [data]

    conversations = []
    for item in conv_list:
        conv = _import_conversation(item)
        if conv:
            conversations.append(conv)
    return conversations


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _detect_model(data: dict) -> str:
    """Detect model from conversation data."""
    if "model" in data:
        return data["model"]
    messages = data.get("turns", data.get("messages", []))
    for msg in messages:
        if msg.get("model"):
            return msg["model"]
    return "gemini"


def _import_conversation(data: dict) -> Optional[Conversation]:
    conv_id = data.get("id") or data.get("conversation_id", str(uuid.uuid4()))
    title = data.get("title", "Untitled Conversation")
    model = _detect_model(data)

    created = _parse_timestamp(data.get("created_at")) or datetime.now()
    updated = _parse_timestamp(data.get("updated_at")) or created

    conv = Conversation(
        id=conv_id,
        title=title,
        source="gemini",
        model=model,
        created_at=created,
        updated_at=updated,
        tags=["google", "gemini"],
    )

    messages = data.get("turns", data.get("messages", []))
    parent_id = None

    for idx, msg_data in enumerate(messages):
        msg_id = msg_data.get("id", f"msg_{idx}")
        role_str = msg_data.get("author", msg_data.get("role", "user"))
        role = "assistant" if role_str.lower() in ("model", "gemini", "bard") else "user"

        content = _extract_content(msg_data)
        if not content:
            content = [text_block("")]

        msg = Message(
            id=msg_id,
            role=role,
            content=content,
            parent_id=parent_id,
            created_at=_parse_timestamp(msg_data.get("timestamp")),
        )
        conv.add_message(msg)
        parent_id = msg_id

    return conv


def _extract_content(msg_data: dict) -> List[Dict[str, Any]]:
    """Extract content blocks from a Gemini message."""
    blocks: List[Dict[str, Any]] = []

    # Gemini uses "parts" for multimodal content
    if "parts" in msg_data:
        for part in msg_data["parts"]:
            if isinstance(part, str):
                blocks.append(text_block(part))
            elif isinstance(part, dict):
                if "text" in part:
                    blocks.append(text_block(part["text"]))
                elif "inline_data" in part:
                    inline = part["inline_data"]
                    blocks.append(
                        media_block(
                            inline.get("mime_type", "image/png"),
                            data=inline.get("data"),
                        )
                    )
        return blocks

    # Fallback: simple text/content field
    text = msg_data.get("content", msg_data.get("text", ""))
    if text:
        blocks.append(text_block(text))
    return blocks
