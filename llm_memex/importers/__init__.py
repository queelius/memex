"""Convention-based importers. Each module provides detect() and import_path()."""
from datetime import datetime
from typing import Any, List, Optional


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a timestamp from various formats (int/float epoch, ISO string)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        try:
            return datetime.fromtimestamp(float(value))
        except (ValueError, OSError):
            pass
    return None


def detect_model(data: dict, message_keys: List[str], default: str) -> str:
    """Detect model from conversation data by scanning top-level then messages.

    Args:
        data: Conversation dict.
        message_keys: Keys to try for the message list (e.g. ["chat_messages", "messages"]).
        default: Fallback model name.
    """
    if "model" in data:
        return data["model"]
    for key in message_keys:
        if key in data:
            for msg in data[key]:
                if msg.get("model"):
                    return msg["model"]
            break
    return default
