"""Import an arkiv archive back into llm-memex.

Arkiv bundles emitted by :mod:`llm_memex.exporters.arkiv_export` (or any other
tool following the arkiv spec, within reason) are read, grouped into
conversations, and converted back into :class:`Conversation` + :class:`Message`
objects.

Supported input layouts (all detected automatically):

- directory with ``conversations.jsonl``, ``README.md``, and ``schema.yaml``
- ``.zip`` file containing those three files
- ``.tar.gz`` / ``.tgz`` file containing those three files

This is intentionally forgiving — if ``README.md`` or ``schema.yaml`` is
missing but ``conversations.jsonl`` is present, we still import. The archive's
"identity as an llm-memex arkiv" is a soft claim; the JSONL records are what
we actually need.

Round-trip fidelity notes:
    The current arkiv format is text-centric (one record per text-bearing
    message). A round-trip DB → arkiv → DB preserves conversations, messages
    (with roles, timestamps, content blocks reconstructed from plain text),
    tags, and message-level notes. It does NOT preserve:

    - Empty messages (e.g. empty system prompts) — filtered out on export.
    - tool_use / thinking / media content blocks — export emits text only.
    - Enrichments (summaries, topics, importance) — not emitted.
    - Provenance (source_type, source_file, source_hash) — not emitted.
    - Conversation-level flags (starred_at, pinned_at, archived_at, sensitive).

    Conversation-level notes are also not currently preserved; only
    message-level notes attached to a specific message round-trip.

    Import uses INSERT OR IGNORE semantics via the Database layer
    (`save_conversation` uses INSERT OR REPLACE, which is idempotent for the
    same conversation_id — re-importing the same arkiv bundle is safe).
"""
from __future__ import annotations

import io
import json
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from llm_memex.models import Conversation, Message, text_block


# ── detection ──────────────────────────────────────────────────

def _jsonl_peek_first_record(reader) -> Optional[Dict[str, Any]]:
    """Return the first parsed JSONL record, or None if unparseable/empty."""
    try:
        for line in reader:
            line = line.strip() if isinstance(line, str) else line.decode("utf-8").strip()
            if not line:
                continue
            rec = json.loads(line)
            return rec if isinstance(rec, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return None


def _is_llm_memex_arkiv_record(rec: Dict[str, Any]) -> bool:
    """Heuristic: does this record look like one of ours?

    A record from llm-memex arkiv export has ``metadata.conversation_id``
    and ``metadata.role``. We're permissive — other arkiv tools may emit
    similar shapes and we're happy to read those too, but we at least want
    these two keys so we can group-and-reconstruct.
    """
    if not isinstance(rec, dict):
        return False
    meta = rec.get("metadata", {})
    if not isinstance(meta, dict):
        return False
    return "conversation_id" in meta and "role" in meta


def detect(path: str) -> bool:
    """Return True if *path* looks like an arkiv bundle we can read."""
    p = Path(path)
    if not p.exists():
        return False

    # Directory layout
    if p.is_dir():
        jsonl = p / "conversations.jsonl"
        if not jsonl.is_file():
            return False
        with open(jsonl, "r", encoding="utf-8") as f:
            rec = _jsonl_peek_first_record(f)
        return rec is not None and _is_llm_memex_arkiv_record(rec)

    # .zip
    if p.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(p) as zf:
                names = set(zf.namelist())
                if "conversations.jsonl" not in names:
                    return False
                with zf.open("conversations.jsonl") as f:
                    rec = _jsonl_peek_first_record(f)
                return rec is not None and _is_llm_memex_arkiv_record(rec)
        except (zipfile.BadZipFile, KeyError):
            return False

    # .tar.gz / .tgz
    lower = str(p).lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        try:
            with tarfile.open(p, "r:gz") as tf:
                try:
                    member = tf.getmember("conversations.jsonl")
                except KeyError:
                    return False
                extracted = tf.extractfile(member)
                if extracted is None:
                    return False
                rec = _jsonl_peek_first_record(extracted)
            return rec is not None and _is_llm_memex_arkiv_record(rec)
        except tarfile.TarError:
            return False

    return False


# ── bundle reading ─────────────────────────────────────────────

def _open_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    """Yield records from the conversations.jsonl inside a bundle."""
    p = Path(path)
    if p.is_dir():
        with open(p / "conversations.jsonl", "r", encoding="utf-8") as f:
            yield from _parse_jsonl_lines(f)
        return
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            with zf.open("conversations.jsonl") as f:
                # ZipFile opens in binary mode; wrap for line iteration.
                text = io.TextIOWrapper(f, encoding="utf-8")
                yield from _parse_jsonl_lines(text)
        return
    lower = str(p).lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        with tarfile.open(p, "r:gz") as tf:
            member = tf.getmember("conversations.jsonl")
            extracted = tf.extractfile(member)
            if extracted is None:
                return
            text = io.TextIOWrapper(extracted, encoding="utf-8")
            yield from _parse_jsonl_lines(text)
        return
    raise ValueError(f"unrecognized arkiv bundle: {path!r}")


def _parse_jsonl_lines(reader) -> Iterable[Dict[str, Any]]:
    for line in reader:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            # Tolerate individual bad lines rather than failing the whole import.
            continue


# ── reconstruction ─────────────────────────────────────────────

def _parse_timestamp(ts: Optional[str]) -> datetime:
    if not ts:
        return datetime.now()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts.replace("Z", "").split("+")[0], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def import_path(path: str) -> List[Conversation]:
    """Import an arkiv bundle. Returns a list of Conversation objects.

    Message ordering within a conversation is by record timestamp (arkiv
    records carry per-message timestamps). Ties are broken by the order
    they appear in the JSONL.
    """
    # Group records by conversation_id. Each bucket preserves record order
    # for stable message sequencing when timestamps tie.
    buckets: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, rec in enumerate(_open_jsonl(path)):
        meta = rec.get("metadata") or {}
        cid = meta.get("conversation_id")
        if not cid:
            continue
        buckets.setdefault(cid, []).append((idx, rec))

    conversations: List[Conversation] = []
    for cid, recs in buckets.items():
        conv = _reconstruct_conversation(cid, recs)
        if conv is not None:
            conversations.append(conv)
    return conversations


def _reconstruct_conversation(
    conv_id: str, recs: List[Tuple[int, Dict[str, Any]]]
) -> Optional[Conversation]:
    """Build a Conversation from grouped records."""
    if not recs:
        return None

    # Pull conversation-level info from the first record that has it;
    # metadata is duplicated per record in the arkiv format, so any will do.
    first_meta = recs[0][1].get("metadata") or {}
    title = first_meta.get("conversation_title")
    source = first_meta.get("source")
    model = first_meta.get("model")
    tags = list(first_meta.get("tags") or [])

    # Sort by (timestamp, original_index) for stable ordering.
    recs_sorted = sorted(
        recs,
        key=lambda t: (t[1].get("timestamp") or "", t[0]),
    )

    first_ts = _parse_timestamp(recs_sorted[0][1].get("timestamp"))
    last_ts = _parse_timestamp(recs_sorted[-1][1].get("timestamp"))

    conv = Conversation(
        id=conv_id,
        created_at=first_ts,
        updated_at=last_ts,
        title=title,
        source=source,
        model=model,
        tags=tags,
    )

    prev_id: Optional[str] = None
    for _, rec in recs_sorted:
        meta = rec.get("metadata") or {}
        msg_id = meta.get("message_id")
        if not msg_id:
            # Synthesize a stable id from conv + index so re-imports match.
            msg_id = f"{conv_id}:{recs_sorted.index((_, rec))}"
        role = meta.get("role") or "unknown"
        content_text = rec.get("content") or ""
        created = _parse_timestamp(rec.get("timestamp"))

        msg = Message(
            id=msg_id,
            role=role,
            content=[text_block(content_text)] if content_text else [],
            parent_id=prev_id,
            created_at=created,
        )
        # message-level notes: preserved as pending marginalia for the CLI to
        # materialize after save_conversation. We stash them in msg.metadata
        # so downstream code can pick them up without a schema change.
        msg_notes = meta.get("notes") or []
        if msg_notes:
            msg.metadata = dict(msg.metadata)
            msg.metadata["_arkiv_notes"] = msg_notes

        # Per-message model overrides conv.model for that message only.
        per_msg_model = meta.get("model")
        if per_msg_model and per_msg_model != conv.model:
            msg.model = per_msg_model

        conv.add_message(msg)
        prev_id = msg_id

    return conv
