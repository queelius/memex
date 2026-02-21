"""Import OpenAI conversation exports (conversations.json)."""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from memex.models import (
    Conversation,
    Message,
    media_block,
    text_block,
    tool_result_block,
    tool_use_block,
)


def detect(path: str) -> bool:
    """Check if file is an OpenAI conversations.json export."""
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list) and data and "mapping" in data[0]:
            return True
        return False
    except (json.JSONDecodeError, IOError, KeyError, IndexError):
        return False


def import_file(path: str) -> List[Conversation]:
    """Import conversations from an OpenAI export file."""
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        data = [data]
    conversations = []
    for item in data:
        conv = _import_conversation(item, path)
        if conv:
            conversations.append(conv)
    return conversations


def _import_conversation(data: dict, source_path: str = None) -> Optional[Conversation]:
    conv_id = data.get("id") or data.get("conversation_id", "")
    mapping = data.get("mapping", {})
    if not mapping:
        return None
    created = (
        datetime.fromtimestamp(data["create_time"])
        if data.get("create_time")
        else datetime.now()
    )
    updated = (
        datetime.fromtimestamp(data["update_time"])
        if data.get("update_time")
        else created
    )
    conv = Conversation(
        id=conv_id,
        title=data.get("title"),
        source="openai",
        created_at=created,
        updated_at=updated,
    )
    model = None
    for node_id, node in mapping.items():
        msg_data = node.get("message")
        if not msg_data:
            continue
        role = msg_data.get("author", {}).get("role", "unknown")
        if role == "system" and not msg_data.get("content", {}).get("parts"):
            continue
        content = _extract_content(msg_data)
        if not content:
            content = [text_block("")]
        msg_model = msg_data.get("metadata", {}).get("model_slug")
        if msg_model and role == "assistant":
            model = msg_model
        parent_id = node.get("parent")
        # Skip virtual root nodes (nodes without messages)
        if parent_id and mapping.get(parent_id, {}).get("message") is None:
            parent_id = None
        msg = Message(
            id=node_id,
            role=role,
            content=content,
            parent_id=parent_id,
            model=msg_model,
            created_at=(
                datetime.fromtimestamp(msg_data["create_time"])
                if msg_data.get("create_time")
                else None
            ),
        )
        conv.add_message(msg)
    conv.model = model
    conv.metadata["_provenance"] = {
        "source_type": "openai",
        "source_file": source_path,
        "source_id": conv_id,
    }
    return conv


def _extract_content(msg_data: dict) -> List[Dict[str, Any]]:
    """Extract content blocks from an OpenAI message."""
    parts = msg_data.get("content", {}).get("parts", [])
    content_type = msg_data.get("content", {}).get("content_type", "text")
    blocks = []

    # Handle tool calls / tool results via metadata
    author_role = msg_data.get("author", {}).get("role", "")
    if content_type == "tether_browsing_display":
        text = "\n".join(str(p) for p in parts if isinstance(p, str))
        if text:
            blocks.append(text_block(text))
        return blocks

    for part in parts:
        if isinstance(part, str):
            blocks.append(text_block(part))
        elif isinstance(part, dict):
            if "asset_pointer" in part:
                blocks.append(
                    media_block("image/png", url=part.get("asset_pointer", ""))
                )
            elif part.get("content_type") == "image_asset_pointer":
                blocks.append(
                    media_block("image/png", url=part.get("asset_pointer", ""))
                )
            elif part.get("type") == "tool_use":
                blocks.append(
                    tool_use_block(
                        id=part.get("id", ""),
                        name=part.get("name", ""),
                        input=part.get("input", {}),
                    )
                )
            elif part.get("type") == "tool_result":
                blocks.append(
                    tool_result_block(
                        tool_use_id=part.get("tool_use_id", ""),
                        content=part.get("content"),
                        is_error=part.get("is_error", False),
                    )
                )
            else:
                blocks.append(text_block(str(part)))
    return blocks
