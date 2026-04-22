"""Export conversations as an arkiv archive (JSONL + README.md + schema.yaml)."""
import json
import os
from datetime import date
from typing import Any, Dict, List

from llm_memex import __version__
from llm_memex.models import Conversation


def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    """Export conversations to an arkiv archive directory.

    Creates a directory at *path* containing:
    - conversations.jsonl  -- one record per message (arkiv universal format)
    - README.md            -- YAML frontmatter (ECHO self-description)
    - schema.yaml          -- metadata key statistics

    Parameters
    ----------
    include_notes : bool
        Include message-level notes in record metadata (default True).
    db : Database | None
        Database instance for querying notes.
    """
    os.makedirs(path, exist_ok=True)

    include_notes = kwargs.get("include_notes", True)
    db = kwargs.get("db")
    records = _build_records(conversations, include_notes=include_notes, db=db)

    # Write JSONL
    jsonl_path = os.path.join(path, "conversations.jsonl")
    with open(jsonl_path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Compute and write schema
    schema = _compute_schema(records)
    _write_schema_yaml(os.path.join(path, "schema.yaml"), schema, len(records))

    # Write README
    _write_readme(
        os.path.join(path, "README.md"),
        num_conversations=len(conversations),
    )


def _build_records(
    conversations: List[Conversation],
    *,
    include_notes: bool = True,
    db: Any = None,
) -> List[Dict[str, Any]]:
    """Convert conversations to arkiv records (one per message)."""
    records = []
    for conv in conversations:
        # Pre-fetch message-level notes for this conversation
        msg_notes: Dict[str, List[Dict[str, Any]]] = {}
        if include_notes and db:
            for note in db.get_notes(
                conversation_id=conv.id, target_kind="message"
            ):
                mid = note.get("message_id")
                if mid:
                    msg_notes.setdefault(mid, []).append(note)

        conv_tags = conv.tags
        for msg in conv.messages.values():
            text = msg.get_text()
            if not text:
                continue

            timestamp = (
                msg.created_at.isoformat()
                if msg.created_at
                else conv.created_at.isoformat()
            )

            metadata: Dict[str, Any] = {"conversation_id": conv.id, "role": msg.role}
            if conv.title:
                metadata["conversation_title"] = conv.title
            if conv.source:
                metadata["source"] = conv.source
            if msg.model:
                metadata["model"] = msg.model
            elif conv.model:
                metadata["model"] = conv.model
            metadata["message_id"] = msg.id
            if conv_tags:
                metadata["tags"] = conv_tags

            # Attach message-level notes
            notes_for_msg = msg_notes.get(msg.id, [])
            if notes_for_msg:
                metadata["notes"] = [
                    {"id": n["id"], "text": n["text"]} for n in notes_for_msg
                ]

            records.append(
                {
                    "mimetype": "text/plain",
                    "content": text,
                    "timestamp": timestamp,
                    "metadata": metadata,
                }
            )
    return records


def _compute_schema(
    records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute metadata key statistics from emitted records.

    For each metadata key, track: type, count, and either enumerated values
    (if ≤20 unique) or a single example (if >20).
    """
    key_stats: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        meta = rec.get("metadata", {})
        for key, value in meta.items():
            if key not in key_stats:
                key_stats[key] = {"type": _json_type(value), "count": 0, "values": set()}
            key_stats[key]["count"] += 1
            # Track unique values (cap collection at 21 to know if >20)
            vals = key_stats[key]["values"]
            if isinstance(vals, set) and len(vals) <= 20:
                vals.add(_hashable(value))

    # Convert sets to lists or pick an example
    result = {}
    for key, stats in key_stats.items():
        entry: Dict[str, Any] = {"type": stats["type"], "count": stats["count"]}
        vals = stats["values"]
        if isinstance(vals, set) and len(vals) <= 20:
            entry["values"] = sorted(str(v) for v in vals)
        else:
            # Pick the first value we collected as an example
            entry["example"] = str(next(iter(vals))) if vals else ""
        result[key] = entry
    return result


def _json_type(value: Any) -> str:
    """Return the JSON type name for a Python value."""
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _hashable(value: Any) -> Any:
    """Make a value hashable for set storage."""
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


def _write_schema_yaml(path: str, schema: Dict[str, Dict[str, Any]], record_count: int) -> None:
    """Write schema.yaml matching arkiv spec format.

    Uses yaml.safe_dump so values containing YAML-special characters
    (quotes, colons, brackets, newlines) are properly escaped.
    """
    import yaml

    metadata_keys: Dict[str, Dict[str, Any]] = {}
    for key, info in schema.items():
        entry: Dict[str, Any] = {
            "type": info["type"],
            "count": info["count"],
        }
        if "values" in info:
            entry["values"] = list(info["values"])
        elif "example" in info:
            entry["example"] = info["example"]
        metadata_keys[key] = entry

    doc = {
        "conversations": {
            "record_count": record_count,
            "metadata_keys": metadata_keys,
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated by llm-memex. Edit freely.\n")
        yaml.safe_dump(
            doc, f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def _write_readme(path: str, num_conversations: int) -> None:
    """Write README.md with YAML frontmatter per arkiv spec."""
    today = date.today().isoformat()
    lines = [
        "---",
        "name: llm-memex conversations archive",
        f"description: \"{num_conversations} conversations exported from llm-memex\"",
        f"datetime: {today}",
        f"generator: llm-memex {__version__}",
        "contents:",
        "  - path: conversations.jsonl",
        "    description: Conversation messages in arkiv universal record format",
        "---",
        "",
        "# llm-memex Conversations Archive",
        "",
        f"This archive contains {num_conversations} conversation(s) exported from llm-memex",
        f"in [arkiv](https://github.com/alonzo-church/arkiv) universal record format.",
        "",
        "Each record in `conversations.jsonl` represents one message with metadata",
        "linking it back to its conversation, speaker role, and source platform.",
        "",
        "To import into arkiv:",
        "",
        "```bash",
        "arkiv import README.md --db archive.db",
        "```",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))
