"""Export conversations as JSON."""
import json
from typing import List

from memex.models import Conversation


def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    """Export conversations to a JSON file.

    Output is a JSON array of conversation objects, each containing
    full message data including content blocks.
    """
    data = []
    for conv in conversations:
        data.append(
            {
                "id": conv.id,
                "title": conv.title,
                "source": conv.source,
                "model": conv.model,
                "tags": conv.tags,
                "created_at": str(conv.created_at),
                "updated_at": str(conv.updated_at),
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "parent_id": m.parent_id,
                        "model": m.model,
                    }
                    for m in conv.messages.values()
                ],
            }
        )
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
