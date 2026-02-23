"""Export conversations as Markdown."""
from typing import List

from memex.models import Conversation


def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    """Export conversations to a Markdown file.

    Each conversation becomes a top-level heading with messages listed below.
    For branching conversations, each path is separated by a horizontal rule.
    """
    lines: List[str] = []
    for conv in conversations:
        lines.append(f"# {conv.title or conv.id}\n")
        if conv.source:
            lines.append(f"*Source: {conv.source}*\n")
        for path_msgs in conv.get_all_paths():
            for msg in path_msgs:
                text = msg.get_content_md()
                lines.append(f"**{msg.role}**: {text}\n")
            lines.append("---\n")
    with open(path, "w") as f:
        f.write("\n".join(lines))
