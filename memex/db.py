"""SQLite database layer for memex. Raw sqlite3 — no ORM."""
from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memex.models import Conversation, Message

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, title TEXT, source TEXT, model TEXT, summary TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
    starred_at DATETIME, pinned_at DATETIME, archived_at DATETIME,
    sensitive BOOLEAN NOT NULL DEFAULT 0,
    metadata JSON NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    id TEXT NOT NULL, role TEXT NOT NULL, parent_id TEXT, model TEXT,
    created_at DATETIME, sensitive BOOLEAN NOT NULL DEFAULT 0,
    content JSON NOT NULL, metadata JSON NOT NULL DEFAULT '{}',
    PRIMARY KEY (conversation_id, id)
);
CREATE TABLE IF NOT EXISTS tags (
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tag TEXT NOT NULL, PRIMARY KEY (conversation_id, tag)
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    conversation_id UNINDEXED, message_id UNINDEXED, text,
    tokenize = 'porter unicode61'
);
CREATE INDEX IF NOT EXISTS idx_conversations_source ON conversations(source);
CREATE INDEX IF NOT EXISTS idx_conversations_model ON conversations(model);
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at);
CREATE INDEX IF NOT EXISTS idx_conversations_starred ON conversations(starred_at) WHERE starred_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_pinned ON conversations(pinned_at) WHERE pinned_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_archived ON conversations(archived_at) WHERE archived_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_parent ON messages(conversation_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
"""


def _dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _encode_cursor(updated_at: str, id: str) -> str:
    return base64.b64encode(
        json.dumps({"u": updated_at, "id": id}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    d = json.loads(base64.b64decode(cursor.encode()).decode())
    return d["u"], d["id"]


class Database:
    def __init__(self, path: str):
        if path == ":memory:":
            self.db_path = ":memory:"
        else:
            db_dir = Path(path)
            db_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(db_dir / "conversations.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = _dict_factory
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript(SCHEMA_SQL)

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def execute_sql(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        if cursor.description is None:
            self.conn.commit()
            return []
        return cursor.fetchall()

    def get_schema(self) -> str:
        rows = self.execute_sql(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
        )
        return "\n\n".join(r["sql"] for r in rows)

    def save_conversation(self, conv: Conversation) -> None:
        c = self.conn.cursor()
        try:
            c.execute(
                "INSERT OR REPLACE INTO conversations "
                "(id,title,source,model,summary,message_count,"
                "created_at,updated_at,starred_at,pinned_at,archived_at,"
                "sensitive,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    conv.id, conv.title, conv.source, conv.model, conv.summary,
                    conv.message_count, _fmt_dt(conv.created_at),
                    _fmt_dt(conv.updated_at), _fmt_dt(conv.starred_at),
                    _fmt_dt(conv.pinned_at), _fmt_dt(conv.archived_at),
                    int(conv.sensitive), json.dumps(conv.metadata),
                ),
            )
            c.execute("DELETE FROM messages WHERE conversation_id=?", (conv.id,))
            c.execute("DELETE FROM tags WHERE conversation_id=?", (conv.id,))
            c.execute(
                "DELETE FROM messages_fts WHERE conversation_id=?", (conv.id,)
            )
            for msg in conv.messages.values():
                c.execute(
                    "INSERT INTO messages "
                    "(conversation_id,id,role,parent_id,model,created_at,"
                    "sensitive,content,metadata) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        conv.id, msg.id, msg.role, msg.parent_id, msg.model,
                        _fmt_dt(msg.created_at), int(msg.sensitive),
                        json.dumps(msg.content), json.dumps(msg.metadata),
                    ),
                )
                text = msg.get_text()
                if text:
                    c.execute(
                        "INSERT INTO messages_fts "
                        "(conversation_id,message_id,text) VALUES (?,?,?)",
                        (conv.id, msg.id, text),
                    )
            for tag in conv.tags:
                c.execute(
                    "INSERT OR IGNORE INTO tags (conversation_id,tag) "
                    "VALUES (?,?)",
                    (conv.id, tag),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def load_conversation(self, id: str) -> Optional[Conversation]:
        rows = self.execute_sql(
            "SELECT * FROM conversations WHERE id=?", (id,)
        )
        if not rows:
            return None
        r = rows[0]
        conv = Conversation(
            id=r["id"],
            created_at=_parse_dt(r["created_at"]),
            updated_at=_parse_dt(r["updated_at"]),
            title=r["title"],
            source=r["source"],
            model=r["model"],
            summary=r["summary"],
            message_count=r["message_count"],
            starred_at=_parse_dt(r["starred_at"]),
            pinned_at=_parse_dt(r["pinned_at"]),
            archived_at=_parse_dt(r["archived_at"]),
            sensitive=bool(r["sensitive"]),
            metadata=json.loads(r["metadata"]) if r["metadata"] else {},
        )
        conv.tags = [
            t["tag"]
            for t in self.execute_sql(
                "SELECT tag FROM tags WHERE conversation_id=?", (id,)
            )
        ]
        for mr in self.execute_sql(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
            (id,),
        ):
            conv.add_message(
                Message(
                    id=mr["id"],
                    role=mr["role"],
                    content=json.loads(mr["content"]) if mr["content"] else [],
                    parent_id=mr["parent_id"],
                    model=mr["model"],
                    created_at=_parse_dt(mr["created_at"]),
                    sensitive=bool(mr["sensitive"]),
                    metadata=(
                        json.loads(mr["metadata"]) if mr["metadata"] else {}
                    ),
                )
            )
        return conv

    def query_conversations(
        self,
        query=None,
        starred=None,
        pinned=None,
        archived=None,
        sensitive=None,
        source=None,
        model=None,
        tag=None,
        before=None,
        after=None,
        limit=20,
        cursor=None,
    ) -> Dict[str, Any]:
        conds: List[str] = []
        params: List[Any] = []
        if query:
            fts_ids = self._fts_search(query)
            if not fts_ids:
                return {"items": [], "next_cursor": None, "has_more": False}
            conds.append(
                f"c.id IN ({','.join('?' for _ in fts_ids)})"
            )
            params.extend(fts_ids)
        if starred is True:
            conds.append("c.starred_at IS NOT NULL")
        elif starred is False:
            conds.append("c.starred_at IS NULL")
        if pinned is True:
            conds.append("c.pinned_at IS NOT NULL")
        elif pinned is False:
            conds.append("c.pinned_at IS NULL")
        if archived is True:
            conds.append("c.archived_at IS NOT NULL")
        elif archived is False:
            conds.append("c.archived_at IS NULL")
        if sensitive is True:
            conds.append("c.sensitive=1")
        elif sensitive is False:
            conds.append("c.sensitive=0")
        if source:
            conds.append("c.source=?")
            params.append(source)
        if model:
            conds.append("c.model=?")
            params.append(model)
        if tag:
            conds.append(
                "EXISTS(SELECT 1 FROM tags t "
                "WHERE t.conversation_id=c.id AND t.tag=?)"
            )
            params.append(tag)
        if before:
            conds.append("c.created_at<?")
            params.append(before)
        if after:
            conds.append("c.created_at>?")
            params.append(after)
        if cursor:
            cdt, cid = _decode_cursor(cursor)
            conds.append(
                "(c.updated_at<? OR (c.updated_at=? AND c.id<?))"
            )
            params.extend([cdt, cdt, cid])
        where = " AND ".join(conds) if conds else "1=1"
        params.append(limit + 1)
        rows = self.execute_sql(
            f"SELECT c.id,c.title,c.source,c.model,c.message_count,"
            f"c.created_at,c.updated_at,c.starred_at,c.pinned_at,"
            f"c.archived_at,c.sensitive,c.summary "
            f"FROM conversations c WHERE {where} "
            f"ORDER BY c.updated_at DESC,c.id DESC LIMIT ?",
            tuple(params),
        )
        has_more = len(rows) > limit
        items = rows[:limit]
        nc = (
            _encode_cursor(items[-1]["updated_at"], items[-1]["id"])
            if has_more and items
            else None
        )
        return {"items": items, "next_cursor": nc, "has_more": has_more}

    def _fts_search(self, query: str) -> List[str]:
        fts_q = " OR ".join(f'"{t}"' for t in query.split())
        try:
            rows = self.execute_sql(
                "SELECT DISTINCT conversation_id FROM messages_fts "
                "WHERE messages_fts MATCH ? LIMIT 1000",
                (fts_q,),
            )
        except sqlite3.OperationalError:
            rows = self.execute_sql(
                "SELECT DISTINCT conversation_id FROM messages "
                "WHERE content LIKE ? LIMIT 1000",
                (f"%{query}%",),
            )
        return [r["conversation_id"] for r in rows]

    def update_conversation(
        self,
        id,
        title=None,
        summary=None,
        starred=None,
        pinned=None,
        archived=None,
        sensitive=None,
        add_tags=None,
        remove_tags=None,
        metadata=None,
    ):
        existing = self.execute_sql(
            "SELECT id,metadata FROM conversations WHERE id=?", (id,)
        )
        if not existing:
            raise ValueError(f"Conversation not found: {id}")
        sets: List[str] = []
        params: List[Any] = []
        now = _fmt_dt(datetime.now())
        if title is not None:
            sets.append("title=?")
            params.append(title)
        if summary is not None:
            sets.append("summary=?")
            params.append(summary)
        if starred is True:
            sets.append("starred_at=?")
            params.append(now)
        elif starred is False:
            sets.append("starred_at=NULL")
        if pinned is True:
            sets.append("pinned_at=?")
            params.append(now)
        elif pinned is False:
            sets.append("pinned_at=NULL")
        if archived is True:
            sets.append("archived_at=?")
            params.append(now)
        elif archived is False:
            sets.append("archived_at=NULL")
        if sensitive is not None:
            sets.append("sensitive=?")
            params.append(int(sensitive))
        if metadata is not None:
            m = json.loads(existing[0]["metadata"] or "{}")
            m.update(metadata)
            sets.append("metadata=?")
            params.append(json.dumps(m))
        if sets:
            sets.append("updated_at=?")
            params.append(now)
            params.append(id)
            self.conn.execute(
                f"UPDATE conversations SET {','.join(sets)} WHERE id=?",
                tuple(params),
            )
        if add_tags:
            for t in add_tags:
                self.conn.execute(
                    "INSERT OR IGNORE INTO tags (conversation_id,tag) "
                    "VALUES (?,?)",
                    (id, t),
                )
        if remove_tags:
            for t in remove_tags:
                self.conn.execute(
                    "DELETE FROM tags WHERE conversation_id=? AND tag=?",
                    (id, t),
                )
        self.conn.commit()

    def append_message(self, conversation_id, message):
        if not self.execute_sql(
            "SELECT id FROM conversations WHERE id=?", (conversation_id,)
        ):
            raise ValueError(f"Conversation not found: {conversation_id}")
        now = _fmt_dt(datetime.now())
        self.conn.execute(
            "INSERT INTO messages "
            "(conversation_id,id,role,parent_id,model,created_at,"
            "sensitive,content,metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                conversation_id, message.id, message.role, message.parent_id,
                message.model, _fmt_dt(message.created_at) or now,
                int(message.sensitive), json.dumps(message.content),
                json.dumps(message.metadata),
            ),
        )
        text = message.get_text()
        if text:
            self.conn.execute(
                "INSERT INTO messages_fts "
                "(conversation_id,message_id,text) VALUES (?,?,?)",
                (conversation_id, message.id, text),
            )
        self.conn.execute(
            "UPDATE conversations SET message_count="
            "(SELECT COUNT(*) FROM messages WHERE conversation_id=?),"
            "updated_at=? WHERE id=?",
            (conversation_id, now, conversation_id),
        )
        self.conn.commit()

    def get_statistics(self):
        tc = self.execute_sql(
            "SELECT COUNT(*) as n FROM conversations"
        )[0]["n"]
        tm = self.execute_sql(
            "SELECT COUNT(*) as n FROM messages"
        )[0]["n"]
        sources = {
            r["source"]: r["n"]
            for r in self.execute_sql(
                "SELECT source,COUNT(*) as n FROM conversations "
                "WHERE source IS NOT NULL GROUP BY source"
            )
        }
        models = {
            r["model"]: r["n"]
            for r in self.execute_sql(
                "SELECT model,COUNT(*) as n FROM conversations "
                "WHERE model IS NOT NULL GROUP BY model"
            )
        }
        tags = {
            r["tag"]: r["n"]
            for r in self.execute_sql(
                "SELECT tag,COUNT(*) as n FROM tags GROUP BY tag"
            )
        }
        return {
            "total_conversations": tc,
            "total_messages": tm,
            "sources": sources,
            "models": models,
            "tags": tags,
        }

    def list_paths(self, conversation_id):
        conv = self.load_conversation(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {conversation_id}")
        result = []
        for i, path in enumerate(conv.get_all_paths()):
            first = path[0] if path else None
            last = path[-1] if path else None
            result.append({
                "index": i,
                "message_count": len(path),
                "first_message": {
                    "id": first.id,
                    "role": first.role,
                    "preview": first.get_text()[:100],
                } if first else None,
                "last_message": {
                    "id": last.id,
                    "role": last.role,
                    "preview": last.get_text()[:100],
                } if last else None,
                "leaf_id": last.id if last else None,
            })
        return result

    def get_path_messages(
        self,
        conversation_id,
        path_index=None,
        leaf_message_id=None,
        offset=0,
        limit=None,
    ):
        conv = self.load_conversation(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {conversation_id}")
        if leaf_message_id:
            path = conv.get_path(leaf_message_id)
            if path is None:
                raise ValueError(f"Message not found: {leaf_message_id}")
        elif path_index is not None:
            all_paths = conv.get_all_paths()
            if path_index < 0 or path_index >= len(all_paths):
                raise ValueError(f"Path index out of range: {path_index}")
            path = all_paths[path_index]
        else:
            all_paths = conv.get_all_paths()
            path = all_paths[0] if all_paths else []
        if offset:
            path = path[offset:]
        if limit is not None:
            path = path[:limit]
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "parent_id": m.parent_id,
                "model": m.model,
                "created_at": _fmt_dt(m.created_at),
                "sensitive": m.sensitive,
                "metadata": m.metadata,
            }
            for m in path
        ]
