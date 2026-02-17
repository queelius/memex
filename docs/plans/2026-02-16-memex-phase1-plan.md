# Memex Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the memex MCP server from scratch — 7 tools, 3 resources, raw sqlite3, FastMCP, multi-DB registry, convention-based import/export, FTS5 search.

**Architecture:** Flat Python package (`memex/`) alongside existing `ctk/`. Raw `sqlite3` database layer. FastMCP server as primary interface. Convention-based importers/exporters with `detect()` + `import_file()`/`export()` contract. Multi-DB registry with YAML config and `ATTACH DATABASE` federation.

**Tech Stack:** Python 3.10+, FastMCP 2.x (`fastmcp<3`), PyYAML, sqlite3 (stdlib), pytest

**Design doc:** `docs/plans/2026-02-16-memex-design.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `memex/__init__.py`, `memex/__main__.py`
- Create: `pyproject.toml`
- Create: `tests/memex/__init__.py`, `tests/memex/conftest.py`

**Step 1: Create directories**

```bash
mkdir -p memex tests/memex
```

**Step 2: Write `memex/__init__.py`**

```python
"""Memex: Personal conversation knowledge base."""
__version__ = "0.1.0"
```

**Step 3: Write `memex/__main__.py`**

```python
"""Allow running as `python -m memex`."""
from memex.cli import main
if __name__ == "__main__":
    main()
```

**Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "memex"
version = "0.1.0"
description = "Personal conversation knowledge base"
requires-python = ">=3.10"
dependencies = [
    "fastmcp<3",
    "pyyaml",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-cov", "pytest-asyncio"]

[project.scripts]
memex = "memex.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests/memex"]
asyncio_mode = "auto"

[tool.setuptools.packages.find]
include = ["memex*"]
```

**Step 5: Write `tests/memex/conftest.py`**

```python
"""Shared fixtures for memex tests."""
import pytest

@pytest.fixture
def tmp_db_path(tmp_path):
    """Path for a temporary database directory."""
    db_dir = tmp_path / "test-db"
    db_dir.mkdir()
    return str(db_dir)
```

**Step 6: Verify**

Run: `python -c "import memex; print(memex.__version__)"` → `0.1.0`
Run: `pytest tests/memex/ -v --co` → no tests yet, collection works

**Step 7: Commit**

```bash
git add memex/ tests/memex/ pyproject.toml
git commit -m "feat(memex): scaffold package structure"
```

---

## Task 2: Content Block Constructors

**Files:**
- Create: `memex/models.py`
- Create: `tests/memex/test_models.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_models.py
from memex.models import text_block, media_block, tool_use_block, tool_result_block, thinking_block

class TestContentBlocks:
    def test_text_block(self):
        assert text_block("hello") == {"type": "text", "text": "hello"}

    def test_media_block_url(self):
        b = media_block("image/png", url="https://example.com/img.png")
        assert b == {"type": "media", "media_type": "image/png", "url": "https://example.com/img.png"}

    def test_media_block_data(self):
        b = media_block("image/jpeg", data="base64data==")
        assert b == {"type": "media", "media_type": "image/jpeg", "data": "base64data=="}

    def test_media_block_filename(self):
        assert media_block("application/pdf", url="x", filename="doc.pdf")["filename"] == "doc.pdf"

    def test_media_block_minimal(self):
        assert media_block("audio/mp3") == {"type": "media", "media_type": "audio/mp3"}

    def test_tool_use_block(self):
        b = tool_use_block("call_1", "search", {"query": "test"})
        assert b == {"type": "tool_use", "id": "call_1", "name": "search", "input": {"query": "test"}}

    def test_tool_result_block(self):
        assert tool_result_block("call_1", content="5 results") == {
            "type": "tool_result", "tool_use_id": "call_1", "content": "5 results"
        }

    def test_tool_result_error(self):
        assert tool_result_block("call_1", content="fail", is_error=True)["is_error"] is True

    def test_tool_result_minimal(self):
        assert tool_result_block("call_1") == {"type": "tool_result", "tool_use_id": "call_1"}

    def test_thinking_block(self):
        assert thinking_block("reasoning...") == {"type": "thinking", "text": "reasoning..."}
```

**Step 2: Run to verify failure**

Run: `pytest tests/memex/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement in `memex/models.py`**

```python
"""Data model for memex conversations."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

ContentBlock = Dict[str, Any]  # Always has "type" key

def text_block(text: str) -> ContentBlock:
    return {"type": "text", "text": text}

def media_block(media_type: str, *, url: str | None = None, data: str | None = None, filename: str | None = None) -> ContentBlock:
    block: ContentBlock = {"type": "media", "media_type": media_type}
    if url is not None: block["url"] = url
    if data is not None: block["data"] = data
    if filename is not None: block["filename"] = filename
    return block

def tool_use_block(id: str, name: str, input: Dict[str, Any]) -> ContentBlock:
    return {"type": "tool_use", "id": id, "name": name, "input": input}

def tool_result_block(tool_use_id: str, content: Any = None, is_error: bool = False) -> ContentBlock:
    block: ContentBlock = {"type": "tool_result", "tool_use_id": tool_use_id}
    if content is not None: block["content"] = content
    if is_error: block["is_error"] = True
    return block

def thinking_block(text: str) -> ContentBlock:
    return {"type": "thinking", "text": text}
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/models.py tests/memex/test_models.py
git commit -m "feat(memex): content block constructors with tests"
```

---

## Task 3: Message and Conversation Dataclasses

**Files:**
- Modify: `memex/models.py`
- Modify: `tests/memex/test_models.py`

**Step 1: Write failing tests for Message**

```python
# Append to tests/memex/test_models.py
from datetime import datetime
from memex.models import Message, Conversation

class TestMessage:
    def test_create_simple(self):
        msg = Message(id="m1", role="user", content=[text_block("hello")])
        assert msg.id == "m1"
        assert msg.parent_id is None
        assert msg.sensitive is False
        assert msg.metadata == {}

    def test_get_text(self):
        msg = Message(id="m1", role="user", content=[text_block("a"), text_block("b")])
        assert msg.get_text() == "a\nb"

    def test_get_text_skips_non_text(self):
        msg = Message(id="m1", role="assistant", content=[
            text_block("before"), tool_use_block("c1", "search", {"q": "x"}), text_block("after"),
        ])
        assert msg.get_text() == "before\nafter"

    def test_get_text_empty(self):
        assert Message(id="m1", role="user", content=[]).get_text() == ""
```

**Step 2: Run to verify failure** → FAIL (Message not defined)

**Step 3: Add Message to `memex/models.py`**

```python
@dataclass
class Message:
    id: str
    role: str
    content: List[ContentBlock]
    parent_id: Optional[str] = None
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    sensitive: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_text(self) -> str:
        return "\n".join(
            block["text"] for block in self.content
            if block.get("type") == "text" and block.get("text")
        )
```

**Step 4: Run tests** → Message tests PASS

**Step 5: Write failing tests for Conversation**

```python
class TestConversation:
    def _linear(self):
        now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        for i, (role, txt) in enumerate([("user","q1"),("assistant","a1"),("user","q2"),("assistant","a2")], 1):
            conv.add_message(Message(
                id=f"m{i}", role=role, content=[text_block(txt)],
                parent_id=f"m{i-1}" if i > 1 else None,
            ))
        return conv

    def test_add_message(self):
        conv = self._linear()
        assert len(conv.messages) == 4
        assert conv.root_ids == ["m1"]
        assert conv.message_count == 4

    def test_get_children(self):
        conv = self._linear()
        assert [c.id for c in conv.get_children("m1")] == ["m2"]
        assert [c.id for c in conv.get_children(None)] == ["m1"]

    def test_get_all_paths_linear(self):
        paths = self._linear().get_all_paths()
        assert len(paths) == 1
        assert [m.id for m in paths[0]] == ["m1", "m2", "m3", "m4"]

    def test_get_all_paths_branching(self):
        now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        conv.add_message(Message(id="m1", role="user", content=[text_block("q")]))
        conv.add_message(Message(id="m2a", role="assistant", content=[text_block("a1")], parent_id="m1"))
        conv.add_message(Message(id="m2b", role="assistant", content=[text_block("a2")], parent_id="m1"))
        paths = conv.get_all_paths()
        assert len(paths) == 2
        assert {tuple(m.id for m in p) for p in paths} == {("m1","m2a"), ("m1","m2b")}

    def test_get_path(self):
        conv = self._linear()
        assert [m.id for m in conv.get_path("m3")] == ["m1", "m2", "m3"]

    def test_get_path_not_found(self):
        assert self._linear().get_path("nope") is None

    def test_get_leaf_ids(self):
        assert self._linear().get_leaf_ids() == ["m4"]
```

**Step 6: Run to verify failure** → FAIL

**Step 7: Add Conversation to `memex/models.py`**

```python
@dataclass
class Conversation:
    id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    source: Optional[str] = None
    model: Optional[str] = None
    summary: Optional[str] = None
    message_count: int = 0
    starred_at: Optional[datetime] = None
    pinned_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    sensitive: bool = False
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: Dict[str, Message] = field(default_factory=dict)
    root_ids: List[str] = field(default_factory=list)
    _children: Dict[Optional[str], List[str]] = field(default_factory=dict, repr=False)

    def add_message(self, message: Message) -> None:
        self.messages[message.id] = message
        self.message_count = len(self.messages)
        if message.parent_id is None and message.id not in self.root_ids:
            self.root_ids.append(message.id)
        self._children.setdefault(message.parent_id, [])
        if message.id not in self._children[message.parent_id]:
            self._children[message.parent_id].append(message.id)

    def get_children(self, message_id: Optional[str]) -> List[Message]:
        return [self.messages[cid] for cid in self._children.get(message_id, []) if cid in self.messages]

    def get_all_paths(self) -> List[List[Message]]:
        paths: List[List[Message]] = []
        def walk(msg_id: str, current: List[Message]):
            current.append(self.messages[msg_id])
            children = self._children.get(msg_id, [])
            if not children:
                paths.append(list(current))
            else:
                for cid in children:
                    walk(cid, current)
            current.pop()
        for rid in self.root_ids:
            walk(rid, [])
        return paths

    def get_path(self, leaf_id: str) -> Optional[List[Message]]:
        if leaf_id not in self.messages:
            return None
        path = []
        current = leaf_id
        while current is not None:
            msg = self.messages.get(current)
            if msg is None: break
            path.append(msg)
            current = msg.parent_id
        path.reverse()
        return path

    def get_leaf_ids(self) -> List[str]:
        has_children = {pid for pid, kids in self._children.items() if kids and pid is not None}
        return [mid for mid in self.messages if mid not in has_children]
```

**Step 8: Run tests** → all PASS

**Step 9: Commit**

```bash
git add memex/models.py tests/memex/test_models.py
git commit -m "feat(memex): Message and Conversation dataclasses with tree navigation"
```

---

## Task 4: Database — Schema and Connection

**Files:**
- Create: `memex/db.py`
- Create: `tests/memex/test_db.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_db.py
from memex.db import Database

class TestDatabaseSchema:
    def test_creates_tables(self, tmp_db_path):
        db = Database(tmp_db_path)
        tables = db.execute_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = [r["name"] for r in tables]
        assert "conversations" in names
        assert "messages" in names
        assert "tags" in names
        assert "messages_fts" in names

    def test_creates_indexes(self, tmp_db_path):
        db = Database(tmp_db_path)
        indexes = db.execute_sql("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        names = [r["name"] for r in indexes]
        assert "idx_conversations_created" in names
        assert "idx_messages_parent" in names
        assert "idx_tags_tag" in names

    def test_wal_mode(self, tmp_db_path):
        db = Database(tmp_db_path)
        assert db.execute_sql("PRAGMA journal_mode")[0]["journal_mode"] == "wal"

    def test_foreign_keys(self, tmp_db_path):
        db = Database(tmp_db_path)
        assert db.execute_sql("PRAGMA foreign_keys")[0]["foreign_keys"] == 1

    def test_close_idempotent(self, tmp_db_path):
        db = Database(tmp_db_path)
        db.close()
        db.close()  # no error

    def test_get_schema(self, tmp_db_path):
        db = Database(tmp_db_path)
        schema = db.get_schema()
        assert "CREATE TABLE conversations" in schema
        assert "CREATE TABLE messages" in schema

    def test_memory_db(self):
        db = Database(":memory:")
        tables = db.execute_sql("SELECT name FROM sqlite_master WHERE type='table'")
        assert len(tables) >= 3
        db.close()

    def test_execute_sql_returns_dicts(self, tmp_db_path):
        db = Database(tmp_db_path)
        rows = db.execute_sql("SELECT 1 as a, 2 as b")
        assert rows == [{"a": 1, "b": 2}]
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement `memex/db.py`**

```python
"""SQLite database layer for memex. Raw sqlite3 — no ORM."""
from __future__ import annotations
import base64, json, sqlite3
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
    if not value: return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try: return datetime.strptime(value, fmt)
        except ValueError: continue
    try: return datetime.fromisoformat(value)
    except ValueError: return None

def _encode_cursor(updated_at: str, id: str) -> str:
    return base64.b64encode(json.dumps({"u": updated_at, "id": id}).encode()).decode()

def _decode_cursor(cursor: str) -> tuple[str, str]:
    d = json.loads(base64.b64decode(cursor.encode()).decode())
    return d["u"], d["id"]

class Database:
    def __init__(self, path: str):
        if path == ":memory:":
            self.db_path = ":memory:"
        else:
            db_dir = Path(path); db_dir.mkdir(parents=True, exist_ok=True)
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
            try: self.conn.close()
            except Exception: pass
            self.conn = None

    def execute_sql(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cursor = self.conn.execute(sql, params)
        if cursor.description is None:
            self.conn.commit(); return []
        return cursor.fetchall()

    def get_schema(self) -> str:
        rows = self.execute_sql("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name")
        return "\n\n".join(r["sql"] for r in rows)
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_db.py
git commit -m "feat(memex): database layer with schema and SQL execution"
```

---

## Task 5: Database — Save and Load Conversations

**Files:**
- Modify: `memex/db.py`
- Modify: `tests/memex/test_db.py`

**Step 1: Write failing tests**

```python
# Append to tests/memex/test_db.py
from datetime import datetime
from memex.models import Conversation, Message, text_block, tool_use_block, tool_result_block

def _make_conv(id="c1", title="Test"):
    now = datetime.now()
    conv = Conversation(id=id, created_at=now, updated_at=now, title=title,
                        source="test", model="gpt-4", tags=["python", "testing"])
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(Message(id="m2", role="assistant", content=[text_block("hi")], parent_id="m1", model="gpt-4"))
    return conv

class TestSaveLoad:
    def test_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        loaded = db.load_conversation("c1")
        assert loaded.title == "Test"
        assert loaded.source == "test"
        assert loaded.message_count == 2
        assert set(loaded.tags) == {"python", "testing"}

    def test_messages_preserved(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        loaded = db.load_conversation("c1")
        assert loaded.messages["m1"].get_text() == "hello"
        assert loaded.messages["m2"].parent_id == "m1"

    def test_tree_structure(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        paths = db.load_conversation("c1").get_all_paths()
        assert [m.id for m in paths[0]] == ["m1", "m2"]

    def test_load_nonexistent(self, tmp_db_path):
        assert Database(tmp_db_path).load_conversation("nope") is None

    def test_save_overwrites(self, tmp_db_path):
        db = Database(tmp_db_path); conv = _make_conv(); db.save_conversation(conv)
        conv.title = "Updated"; db.save_conversation(conv)
        assert db.load_conversation("c1").title == "Updated"

    def test_metadata_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path); conv = _make_conv(); conv.metadata = {"q": 0.9}
        db.save_conversation(conv)
        assert db.load_conversation("c1").metadata == {"q": 0.9}

    def test_sensitive_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path); conv = _make_conv(); conv.sensitive = True
        db.save_conversation(conv)
        assert db.load_conversation("c1").sensitive is True

    def test_content_blocks_roundtrip(self, tmp_db_path):
        db = Database(tmp_db_path); now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        conv.add_message(Message(id="m1", role="assistant", content=[
            text_block("searching"), tool_use_block("c1", "search", {"q": "test"}),
        ]))
        conv.add_message(Message(id="m2", role="tool", content=[
            tool_result_block("c1", content="found 5"),
        ], parent_id="m1"))
        db.save_conversation(conv)
        m1 = db.load_conversation("c1").messages["m1"]
        assert m1.content[1]["type"] == "tool_use"
        assert m1.content[1]["name"] == "search"
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Add `save_conversation` and `load_conversation` to `Database` class**

```python
    def save_conversation(self, conv: Conversation) -> None:
        c = self.conn.cursor()
        try:
            c.execute("INSERT OR REPLACE INTO conversations (id,title,source,model,summary,message_count,created_at,updated_at,starred_at,pinned_at,archived_at,sensitive,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (conv.id, conv.title, conv.source, conv.model, conv.summary, conv.message_count,
                 _fmt_dt(conv.created_at), _fmt_dt(conv.updated_at), _fmt_dt(conv.starred_at),
                 _fmt_dt(conv.pinned_at), _fmt_dt(conv.archived_at), int(conv.sensitive), json.dumps(conv.metadata)))
            c.execute("DELETE FROM messages WHERE conversation_id=?", (conv.id,))
            c.execute("DELETE FROM tags WHERE conversation_id=?", (conv.id,))
            c.execute("DELETE FROM messages_fts WHERE conversation_id=?", (conv.id,))
            for msg in conv.messages.values():
                c.execute("INSERT INTO messages (conversation_id,id,role,parent_id,model,created_at,sensitive,content,metadata) VALUES (?,?,?,?,?,?,?,?,?)",
                    (conv.id, msg.id, msg.role, msg.parent_id, msg.model, _fmt_dt(msg.created_at),
                     int(msg.sensitive), json.dumps(msg.content), json.dumps(msg.metadata)))
                text = msg.get_text()
                if text:
                    c.execute("INSERT INTO messages_fts (conversation_id,message_id,text) VALUES (?,?,?)", (conv.id, msg.id, text))
            for tag in conv.tags:
                c.execute("INSERT OR IGNORE INTO tags (conversation_id,tag) VALUES (?,?)", (conv.id, tag))
            self.conn.commit()
        except Exception:
            self.conn.rollback(); raise

    def load_conversation(self, id: str) -> Optional[Conversation]:
        rows = self.execute_sql("SELECT * FROM conversations WHERE id=?", (id,))
        if not rows: return None
        r = rows[0]
        conv = Conversation(id=r["id"], created_at=_parse_dt(r["created_at"]), updated_at=_parse_dt(r["updated_at"]),
            title=r["title"], source=r["source"], model=r["model"], summary=r["summary"],
            message_count=r["message_count"], starred_at=_parse_dt(r["starred_at"]),
            pinned_at=_parse_dt(r["pinned_at"]), archived_at=_parse_dt(r["archived_at"]),
            sensitive=bool(r["sensitive"]), metadata=json.loads(r["metadata"]) if r["metadata"] else {})
        conv.tags = [t["tag"] for t in self.execute_sql("SELECT tag FROM tags WHERE conversation_id=?", (id,))]
        for mr in self.execute_sql("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (id,)):
            conv.add_message(Message(id=mr["id"], role=mr["role"],
                content=json.loads(mr["content"]) if mr["content"] else [],
                parent_id=mr["parent_id"], model=mr["model"], created_at=_parse_dt(mr["created_at"]),
                sensitive=bool(mr["sensitive"]), metadata=json.loads(mr["metadata"]) if mr["metadata"] else {}))
        return conv
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_db.py
git commit -m "feat(memex): save and load conversations with tree + FTS indexing"
```

---

## Task 6: Database — Search and Query

**Files:**
- Modify: `memex/db.py`
- Modify: `tests/memex/test_db.py`

**Step 1: Write failing tests**

```python
def _populate_db(db):
    for i in range(1, 6):
        now = datetime(2024, 1, i)
        conv = Conversation(id=f"c{i}", created_at=now, updated_at=now, title=f"Chat {i}",
            source="openai" if i <= 3 else "anthropic", model="gpt-4" if i <= 3 else "claude-3",
            tags=["python"] if i % 2 == 0 else ["rust"])
        if i == 1: conv.starred_at = now
        if i == 2: conv.pinned_at = now
        if i == 3: conv.archived_at = now
        conv.add_message(Message(id="m1", role="user", content=[text_block(f"topic {i}")]))
        conv.add_message(Message(id="m2", role="assistant", content=[text_block(f"answer {i}")], parent_id="m1"))
        db.save_conversation(conv)

class TestQuery:
    def test_all(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        assert len(db.query_conversations()["items"]) == 5

    def test_limit(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        r = db.query_conversations(limit=2)
        assert len(r["items"]) == 2 and r["has_more"] is True

    def test_starred(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        r = db.query_conversations(starred=True)
        assert len(r["items"]) == 1 and r["items"][0]["id"] == "c1"

    def test_source(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        assert len(db.query_conversations(source="anthropic")["items"]) == 2

    def test_tag(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        assert len(db.query_conversations(tag="python")["items"]) == 2

    def test_not_archived(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        assert len(db.query_conversations(archived=False)["items"]) == 4

class TestSearch:
    def test_fts(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        r = db.query_conversations(query="topic 3")
        assert "c3" in [i["id"] for i in r["items"]]

    def test_no_results(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        assert len(db.query_conversations(query="nonexistent_xyz")["items"]) == 0

    def test_with_filter(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        r = db.query_conversations(query="topic", source="anthropic")
        for item in r["items"]:
            assert item["id"] in ("c4", "c5")
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Add `query_conversations` and `_fts_search` to `Database`**

```python
    def query_conversations(self, query=None, starred=None, pinned=None, archived=None,
            sensitive=None, source=None, model=None, tag=None, before=None, after=None,
            limit=20, cursor=None) -> Dict[str, Any]:
        conds, params = [], []
        if query:
            fts_ids = self._fts_search(query)
            if not fts_ids: return {"items": [], "next_cursor": None, "has_more": False}
            conds.append(f"c.id IN ({','.join('?' for _ in fts_ids)})"); params.extend(fts_ids)
        if starred is True: conds.append("c.starred_at IS NOT NULL")
        elif starred is False: conds.append("c.starred_at IS NULL")
        if pinned is True: conds.append("c.pinned_at IS NOT NULL")
        elif pinned is False: conds.append("c.pinned_at IS NULL")
        if archived is True: conds.append("c.archived_at IS NOT NULL")
        elif archived is False: conds.append("c.archived_at IS NULL")
        if sensitive is True: conds.append("c.sensitive=1")
        elif sensitive is False: conds.append("c.sensitive=0")
        if source: conds.append("c.source=?"); params.append(source)
        if model: conds.append("c.model=?"); params.append(model)
        if tag: conds.append("EXISTS(SELECT 1 FROM tags t WHERE t.conversation_id=c.id AND t.tag=?)"); params.append(tag)
        if before: conds.append("c.created_at<?"); params.append(before)
        if after: conds.append("c.created_at>?"); params.append(after)
        if cursor:
            cdt, cid = _decode_cursor(cursor)
            conds.append("(c.updated_at<? OR (c.updated_at=? AND c.id<?))"); params.extend([cdt, cdt, cid])
        where = " AND ".join(conds) if conds else "1=1"
        params.append(limit + 1)
        rows = self.execute_sql(f"SELECT c.id,c.title,c.source,c.model,c.message_count,c.created_at,c.updated_at,c.starred_at,c.pinned_at,c.archived_at,c.sensitive,c.summary FROM conversations c WHERE {where} ORDER BY c.updated_at DESC,c.id DESC LIMIT ?", tuple(params))
        has_more = len(rows) > limit; items = rows[:limit]
        nc = _encode_cursor(items[-1]["updated_at"], items[-1]["id"]) if has_more and items else None
        return {"items": items, "next_cursor": nc, "has_more": has_more}

    def _fts_search(self, query: str) -> List[str]:
        fts_q = " OR ".join(f'"{t}"' for t in query.split())
        try:
            rows = self.execute_sql("SELECT DISTINCT conversation_id FROM messages_fts WHERE messages_fts MATCH ? LIMIT 1000", (fts_q,))
        except sqlite3.OperationalError:
            rows = self.execute_sql("SELECT DISTINCT conversation_id FROM messages WHERE content LIKE ? LIMIT 1000", (f"%{query}%",))
        return [r["conversation_id"] for r in rows]
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_db.py
git commit -m "feat(memex): query_conversations with FTS5 search, filters, pagination"
```

---

## Task 7: Database — Update and Append

**Files:**
- Modify: `memex/db.py`
- Modify: `tests/memex/test_db.py`

**Step 1: Write failing tests**

```python
import pytest

class TestUpdate:
    def test_title(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.update_conversation("c1", title="New"); assert db.load_conversation("c1").title == "New"

    def test_star_unstar(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.update_conversation("c1", starred=True); assert db.load_conversation("c1").starred_at is not None
        db.update_conversation("c1", starred=False); assert db.load_conversation("c1").starred_at is None

    def test_add_remove_tags(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.update_conversation("c1", add_tags=["new"]); assert "new" in db.load_conversation("c1").tags
        db.update_conversation("c1", remove_tags=["python"]); assert "python" not in db.load_conversation("c1").tags

    def test_metadata_merge(self, tmp_db_path):
        db = Database(tmp_db_path); conv = _make_conv(); conv.metadata = {"a": 1}; db.save_conversation(conv)
        db.update_conversation("c1", metadata={"b": 2})
        assert db.load_conversation("c1").metadata == {"a": 1, "b": 2}

    def test_summary(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.update_conversation("c1", summary="A test."); assert db.load_conversation("c1").summary == "A test."

    def test_nonexistent(self, tmp_db_path):
        with pytest.raises(ValueError, match="not found"):
            Database(tmp_db_path).update_conversation("nope", title="x")

class TestAppend:
    def test_append(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.append_message("c1", Message(id="m3", role="user", content=[text_block("followup")], parent_id="m2"))
        loaded = db.load_conversation("c1")
        assert len(loaded.messages) == 3 and loaded.message_count == 3

    def test_branch(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.append_message("c1", Message(id="m2b", role="assistant", content=[text_block("alt")], parent_id="m1"))
        assert len(db.load_conversation("c1").get_all_paths()) == 2

    def test_nonexistent(self, tmp_db_path):
        with pytest.raises(ValueError, match="not found"):
            Database(tmp_db_path).append_message("nope", Message(id="m1", role="user", content=[text_block("x")]))

    def test_updates_fts(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        db.append_message("c1", Message(id="m3", role="user", content=[text_block("unique_xyz_term")], parent_id="m2"))
        assert len(db.query_conversations(query="unique_xyz_term")["items"]) == 1
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Add `update_conversation` and `append_message` to `Database`**

```python
    def update_conversation(self, id, title=None, summary=None, starred=None, pinned=None,
            archived=None, sensitive=None, add_tags=None, remove_tags=None, metadata=None):
        existing = self.execute_sql("SELECT id,metadata FROM conversations WHERE id=?", (id,))
        if not existing: raise ValueError(f"Conversation not found: {id}")
        sets, params = [], []; now = _fmt_dt(datetime.now())
        if title is not None: sets.append("title=?"); params.append(title)
        if summary is not None: sets.append("summary=?"); params.append(summary)
        if starred is True: sets.append("starred_at=?"); params.append(now)
        elif starred is False: sets.append("starred_at=NULL")
        if pinned is True: sets.append("pinned_at=?"); params.append(now)
        elif pinned is False: sets.append("pinned_at=NULL")
        if archived is True: sets.append("archived_at=?"); params.append(now)
        elif archived is False: sets.append("archived_at=NULL")
        if sensitive is not None: sets.append("sensitive=?"); params.append(int(sensitive))
        if metadata is not None:
            m = json.loads(existing[0]["metadata"] or "{}"); m.update(metadata)
            sets.append("metadata=?"); params.append(json.dumps(m))
        if sets:
            sets.append("updated_at=?"); params.append(now); params.append(id)
            self.conn.execute(f"UPDATE conversations SET {','.join(sets)} WHERE id=?", tuple(params))
        if add_tags:
            for t in add_tags: self.conn.execute("INSERT OR IGNORE INTO tags (conversation_id,tag) VALUES (?,?)", (id, t))
        if remove_tags:
            for t in remove_tags: self.conn.execute("DELETE FROM tags WHERE conversation_id=? AND tag=?", (id, t))
        self.conn.commit()

    def append_message(self, conversation_id, message):
        if not self.execute_sql("SELECT id FROM conversations WHERE id=?", (conversation_id,)):
            raise ValueError(f"Conversation not found: {conversation_id}")
        now = _fmt_dt(datetime.now())
        self.conn.execute("INSERT INTO messages (conversation_id,id,role,parent_id,model,created_at,sensitive,content,metadata) VALUES (?,?,?,?,?,?,?,?,?)",
            (conversation_id, message.id, message.role, message.parent_id, message.model,
             _fmt_dt(message.created_at) or now, int(message.sensitive), json.dumps(message.content), json.dumps(message.metadata)))
        text = message.get_text()
        if text: self.conn.execute("INSERT INTO messages_fts (conversation_id,message_id,text) VALUES (?,?,?)", (conversation_id, message.id, text))
        self.conn.execute("UPDATE conversations SET message_count=(SELECT COUNT(*) FROM messages WHERE conversation_id=?),updated_at=? WHERE id=?",
            (conversation_id, now, conversation_id))
        self.conn.commit()
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_db.py
git commit -m "feat(memex): update_conversation and append_message"
```

---

## Task 8: Database — Statistics and Path Navigation

**Files:**
- Modify: `memex/db.py`
- Modify: `tests/memex/test_db.py`

**Step 1: Write failing tests**

```python
class TestStatistics:
    def test_stats(self, tmp_db_path):
        db = Database(tmp_db_path); _populate_db(db)
        s = db.get_statistics()
        assert s["total_conversations"] == 5 and s["total_messages"] == 10
        assert "openai" in s["sources"] and "anthropic" in s["sources"]

    def test_stats_empty(self, tmp_db_path):
        s = Database(tmp_db_path).get_statistics()
        assert s["total_conversations"] == 0

class TestPaths:
    def test_list_paths(self, tmp_db_path):
        db = Database(tmp_db_path); now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        conv.add_message(Message(id="m1", role="user", content=[text_block("q")]))
        conv.add_message(Message(id="m2a", role="assistant", content=[text_block("a1")], parent_id="m1"))
        conv.add_message(Message(id="m2b", role="assistant", content=[text_block("a2")], parent_id="m1"))
        db.save_conversation(conv)
        paths = db.list_paths("c1")
        assert len(paths) == 2 and paths[0]["index"] == 0

    def test_get_path_messages(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        msgs = db.get_path_messages("c1", path_index=0)
        assert len(msgs) == 2 and msgs[0]["role"] == "user"

    def test_get_path_by_leaf(self, tmp_db_path):
        db = Database(tmp_db_path); db.save_conversation(_make_conv())
        msgs = db.get_path_messages("c1", leaf_message_id="m2")
        assert len(msgs) == 2

    def test_get_path_offset_limit(self, tmp_db_path):
        db = Database(tmp_db_path); now = datetime.now()
        conv = Conversation(id="c1", created_at=now, updated_at=now)
        for i in range(1, 6):
            conv.add_message(Message(id=f"m{i}", role="user" if i%2 else "assistant",
                content=[text_block(f"msg{i}")], parent_id=f"m{i-1}" if i > 1 else None))
        db.save_conversation(conv)
        msgs = db.get_path_messages("c1", path_index=0, offset=1, limit=2)
        assert len(msgs) == 2 and msgs[0]["id"] == "m2"

    def test_list_paths_not_found(self, tmp_db_path):
        with pytest.raises(ValueError): Database(tmp_db_path).list_paths("nope")
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Add `get_statistics`, `list_paths`, `get_path_messages` to `Database`**

```python
    def get_statistics(self):
        tc = self.execute_sql("SELECT COUNT(*) as n FROM conversations")[0]["n"]
        tm = self.execute_sql("SELECT COUNT(*) as n FROM messages")[0]["n"]
        sources = {r["source"]: r["n"] for r in self.execute_sql("SELECT source,COUNT(*) as n FROM conversations WHERE source IS NOT NULL GROUP BY source")}
        models = {r["model"]: r["n"] for r in self.execute_sql("SELECT model,COUNT(*) as n FROM conversations WHERE model IS NOT NULL GROUP BY model")}
        tags = {r["tag"]: r["n"] for r in self.execute_sql("SELECT tag,COUNT(*) as n FROM tags GROUP BY tag")}
        return {"total_conversations": tc, "total_messages": tm, "sources": sources, "models": models, "tags": tags}

    def list_paths(self, conversation_id):
        conv = self.load_conversation(conversation_id)
        if conv is None: raise ValueError(f"Conversation not found: {conversation_id}")
        result = []
        for i, path in enumerate(conv.get_all_paths()):
            first, last = (path[0] if path else None), (path[-1] if path else None)
            result.append({"index": i, "message_count": len(path),
                "first_message": {"id": first.id, "role": first.role, "preview": first.get_text()[:100]} if first else None,
                "last_message": {"id": last.id, "role": last.role, "preview": last.get_text()[:100]} if last else None,
                "leaf_id": last.id if last else None})
        return result

    def get_path_messages(self, conversation_id, path_index=None, leaf_message_id=None, offset=0, limit=None):
        conv = self.load_conversation(conversation_id)
        if conv is None: raise ValueError(f"Conversation not found: {conversation_id}")
        if leaf_message_id:
            path = conv.get_path(leaf_message_id)
            if path is None: raise ValueError(f"Message not found: {leaf_message_id}")
        elif path_index is not None:
            all_paths = conv.get_all_paths()
            if path_index < 0 or path_index >= len(all_paths): raise ValueError(f"Path index out of range: {path_index}")
            path = all_paths[path_index]
        else:
            all_paths = conv.get_all_paths(); path = all_paths[0] if all_paths else []
        if offset: path = path[offset:]
        if limit is not None: path = path[:limit]
        return [{"id": m.id, "role": m.role, "content": m.content, "parent_id": m.parent_id,
                 "model": m.model, "created_at": _fmt_dt(m.created_at), "sensitive": m.sensitive, "metadata": m.metadata} for m in path]
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/db.py tests/memex/test_db.py
git commit -m "feat(memex): statistics, list_paths, get_path_messages"
```

---

## Task 9: Config — YAML Loading and Database Registry

**Files:**
- Create: `memex/config.py`
- Create: `tests/memex/test_config.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_config.py
import os
import pytest
from memex.config import load_config, DatabaseRegistry

class TestLoadConfig:
    def test_from_yaml(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("databases:\n  main:\n    path: /tmp/main\nprimary: main\n")
        config = load_config(str(cfg))
        assert "main" in config["databases"]
        assert config["primary"] == "main"

    def test_single_db_env(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "single")
        monkeypatch.setenv("MEMEX_DATABASE_PATH", db_path)
        config = load_config(None)
        assert "default" in config["databases"]
        assert config["primary"] == "default"

    def test_missing_config_no_env(self):
        config = load_config("/nonexistent/config.yaml")
        assert config["databases"] == {}

    def test_sql_write_default_false(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("databases: {}\n")
        assert load_config(str(cfg))["sql_write"] is False

    def test_sql_write_env_override(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("databases: {}\nsql_write: false\n")
        monkeypatch.setenv("MEMEX_SQL_WRITE", "true")
        assert load_config(str(cfg))["sql_write"] is True

class TestDatabaseRegistry:
    def test_single_db(self, tmp_path):
        reg = DatabaseRegistry({"databases": {"main": {"path": str(tmp_path / "main")}}, "primary": "main", "sql_write": False})
        db = reg.get_db("main")
        assert db is not None
        reg.close()

    def test_get_db_default(self, tmp_path):
        reg = DatabaseRegistry({"databases": {"main": {"path": str(tmp_path / "main")}}, "primary": "main", "sql_write": False})
        assert reg.get_db(None) is reg.get_db("main")
        reg.close()

    def test_get_db_unknown(self, tmp_path):
        reg = DatabaseRegistry({"databases": {"main": {"path": str(tmp_path / "main")}}, "primary": "main", "sql_write": False})
        with pytest.raises(ValueError, match="Unknown database"):
            reg.get_db("nope")
        reg.close()

    def test_all_dbs(self, tmp_path):
        reg = DatabaseRegistry({"databases": {
            "a": {"path": str(tmp_path / "a")},
            "b": {"path": str(tmp_path / "b")},
        }, "primary": "a", "sql_write": False})
        assert len(reg.all_dbs()) == 2
        reg.close()
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement `memex/config.py`**

```python
"""Configuration and multi-database registry."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from memex.db import Database

def load_config(config_path: str | None = None) -> Dict[str, Any]:
    config = {"databases": {}, "primary": None, "sql_write": False}
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            loaded = yaml.safe_load(f) or {}
        config.update(loaded)
    elif (env_path := os.environ.get("MEMEX_DATABASE_PATH")):
        config["databases"] = {"default": {"path": env_path}}
        config["primary"] = "default"
    if os.environ.get("MEMEX_SQL_WRITE", "").lower() in ("true", "1", "yes"):
        config["sql_write"] = True
    return config

class DatabaseRegistry:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.primary = config.get("primary")
        self.sql_write = config.get("sql_write", False)
        self._dbs: Dict[str, Database] = {}
        for name, db_config in config.get("databases", {}).items():
            path = os.path.expanduser(db_config["path"])
            self._dbs[name] = Database(path)

    def get_db(self, name: str | None = None) -> Database:
        if name is None: name = self.primary
        if name not in self._dbs: raise ValueError(f"Unknown database: {name}")
        return self._dbs[name]

    def all_dbs(self) -> Dict[str, Database]:
        return dict(self._dbs)

    def close(self):
        for db in self._dbs.values(): db.close()
        self._dbs.clear()
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/config.py tests/memex/test_config.py
git commit -m "feat(memex): YAML config loading and DatabaseRegistry"
```

---

## Task 10: MCP Server — Lifespan and SQL Tool

**Files:**
- Create: `memex/server.py`
- Create: `tests/memex/test_server.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_server.py
import pytest
from datetime import datetime
from memex.db import Database
from memex.models import Conversation, Message, text_block
from memex.server import create_server

@pytest.fixture
def db(tmp_db_path):
    d = Database(tmp_db_path)
    now = datetime.now()
    conv = Conversation(id="c1", created_at=now, updated_at=now, title="Test", source="openai", tags=["python"])
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(Message(id="m2", role="assistant", content=[text_block("hi")], parent_id="m1"))
    d.save_conversation(conv)
    return d

class TestExecuteSQL:
    @pytest.mark.asyncio
    async def test_select(self, db):
        server = create_server(db)
        # Call the tool function directly (FastMCP tools are regular functions)
        from memex.server import execute_sql as _execute_sql
        # We'll test via the database directly since tool functions need Context
        result = db.execute_sql("SELECT id, title FROM conversations")
        assert len(result) == 1 and result[0]["id"] == "c1"

    def test_read_only_by_default(self, db):
        # SQL write should fail when sql_write=False
        with pytest.raises(Exception):
            db.execute_sql("DROP TABLE conversations")
```

Note: Full MCP tool testing requires a FastMCP test client. For Phase 1, we test
the database methods that tools call, plus a basic server creation smoke test.
Integration testing of the MCP protocol is Task 15.

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement `memex/server.py` with lifespan and execute_sql**

```python
"""Memex MCP server — the primary interface."""
from __future__ import annotations
import json
from contextlib import asynccontextmanager
from typing import Annotated, Any, Optional
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from memex.config import load_config, DatabaseRegistry

@asynccontextmanager
async def lifespan(server):
    import os
    config_path = os.environ.get("MEMEX_CONFIG")
    config = load_config(config_path)
    registry = DatabaseRegistry(config)
    try:
        yield {"registry": registry}
    finally:
        registry.close()

def create_server(db=None, sql_write=False):
    """Create the MCP server. Pass db for testing (skips lifespan)."""
    mcp = FastMCP("memex", lifespan=lifespan if db is None else None)
    if db is not None:
        # Testing mode: inject db directly
        mcp._test_db = db
        mcp._test_sql_write = sql_write
    _register_tools(mcp)
    _register_resources(mcp)
    return mcp

def _get_registry(ctx: Context) -> DatabaseRegistry:
    return ctx.lifespan_context["registry"]

def _get_db(ctx: Context, db_name: str | None = None):
    return _get_registry(ctx).get_db(db_name)

def _register_tools(mcp: FastMCP):

    @mcp.tool(annotations={"readOnlyHint": True})
    def execute_sql(
        sql: Annotated[str, Field(description="SQL query to execute")],
        db: Annotated[str | None, Field(description="Target database name")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Run a SQL query against the database. Read-only by default."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        sql_write = (ctx and _get_registry(ctx).sql_write) if ctx and hasattr(ctx, 'lifespan_context') else getattr(mcp, '_test_sql_write', False)
        sql_stripped = sql.strip().upper()
        if not sql_write and not sql_stripped.startswith("SELECT") and not sql_stripped.startswith("PRAGMA"):
            raise ToolError("SQL writes are disabled. Set MEMEX_SQL_WRITE=true to enable.")
        try:
            return database.execute_sql(sql)
        except Exception as e:
            raise ToolError(str(e))

    # Remaining tools added in Tasks 11-13

def _register_resources(mcp: FastMCP):
    pass  # Added in Task 14

# Entry point
def main():
    import os
    config_path = os.environ.get("MEMEX_CONFIG")
    config = load_config(config_path)
    mcp = FastMCP("memex", lifespan=lifespan)
    _register_tools(mcp)
    _register_resources(mcp)
    mcp.run()
```

**Step 4: Run tests** → PASS

**Step 5: Commit**

```bash
git add memex/server.py tests/memex/test_server.py
git commit -m "feat(memex): MCP server with lifespan and execute_sql tool"
```

---

## Task 11: MCP Server — Query, Update, Append, Export Tools

**Files:**
- Modify: `memex/server.py`
- Modify: `tests/memex/test_server.py`

**Step 1: Write failing tests**

```python
# Append to tests/memex/test_server.py

class TestQueryTool:
    def test_query_all(self, db):
        result = db.query_conversations()
        assert len(result["items"]) == 1

    def test_query_by_tag(self, db):
        result = db.query_conversations(tag="python")
        assert len(result["items"]) == 1

class TestUpdateTool:
    def test_star(self, db):
        db.update_conversation("c1", starred=True)
        assert db.load_conversation("c1").starred_at is not None

class TestAppendTool:
    def test_append(self, db):
        db.append_message("c1", Message(id="m3", role="user", content=[text_block("more")], parent_id="m2"))
        assert db.load_conversation("c1").message_count == 3
```

**Step 2: Run to verify failure** → these should PASS since they test db methods directly

**Step 3: Add remaining tools to `_register_tools` in `memex/server.py`**

```python
    @mcp.tool(annotations={"readOnlyHint": True})
    def query_conversations(
        query: Annotated[str | None, Field(description="FTS5 search text")] = None,
        starred: Annotated[bool | None, Field(description="Filter by starred")] = None,
        pinned: Annotated[bool | None, Field(description="Filter by pinned")] = None,
        archived: Annotated[bool | None, Field(description="Filter by archived")] = None,
        sensitive: Annotated[bool | None, Field(description="Filter by sensitive")] = None,
        source: Annotated[str | None, Field(description="Filter by source")] = None,
        model: Annotated[str | None, Field(description="Filter by model")] = None,
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict:
        """Search and list conversations. FTS5 when query provided, otherwise chronological."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        return database.query_conversations(
            query=query, starred=starred, pinned=pinned, archived=archived,
            sensitive=sensitive, source=source, model=model, tag=tag,
            limit=limit, cursor=cursor,
        )

    @mcp.tool(annotations={"readOnlyHint": True})
    def list_paths(
        id: Annotated[str, Field(description="Conversation ID")],
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """List all root-to-leaf paths in a conversation tree."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        try: return database.list_paths(id)
        except ValueError as e: raise ToolError(str(e))

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_path_messages(
        id: Annotated[str, Field(description="Conversation ID")],
        path_index: Annotated[int | None, Field(description="Path index from list_paths")] = None,
        leaf_message_id: Annotated[str | None, Field(description="Leaf message ID")] = None,
        offset: Annotated[int, Field(description="Skip first N messages")] = 0,
        limit: Annotated[int | None, Field(description="Max messages to return")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Get messages along a specific path in the conversation tree."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        try: return database.get_path_messages(id, path_index=path_index, leaf_message_id=leaf_message_id, offset=offset, limit=limit)
        except ValueError as e: raise ToolError(str(e))

    @mcp.tool(annotations={"idempotentHint": True})
    def update_conversation(
        id: Annotated[str, Field(description="Conversation ID")],
        title: Annotated[str | None, Field(description="New title")] = None,
        summary: Annotated[str | None, Field(description="New summary")] = None,
        starred: Annotated[bool | None, Field(description="Star/unstar")] = None,
        pinned: Annotated[bool | None, Field(description="Pin/unpin")] = None,
        archived: Annotated[bool | None, Field(description="Archive/unarchive")] = None,
        sensitive: Annotated[bool | None, Field(description="Mark sensitive")] = None,
        add_tags: Annotated[list[str] | None, Field(description="Tags to add")] = None,
        remove_tags: Annotated[list[str] | None, Field(description="Tags to remove")] = None,
        metadata: Annotated[dict | None, Field(description="Metadata to merge")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict:
        """Update conversation properties. Only provided fields change."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        try:
            database.update_conversation(id, title=title, summary=summary, starred=starred,
                pinned=pinned, archived=archived, sensitive=sensitive,
                add_tags=add_tags, remove_tags=remove_tags, metadata=metadata)
            return {"updated": id}
        except ValueError as e: raise ToolError(str(e))

    @mcp.tool()
    def append_message(
        conversation_id: Annotated[str, Field(description="Conversation ID")],
        role: Annotated[str, Field(description="Message role: user, assistant, system, tool")],
        content: Annotated[list[dict], Field(description="Content blocks array")],
        parent_message_id: Annotated[str | None, Field(description="Parent message ID (leaf=extend, non-leaf=branch)")] = None,
        message_model: Annotated[str | None, Field(description="Model that generated this message")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict:
        """Add a message to the conversation tree."""
        import uuid
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        msg_id = str(uuid.uuid4())[:8]
        msg = Message(id=msg_id, role=role, content=content, parent_id=parent_message_id, model=message_model)
        try:
            database.append_message(conversation_id, msg)
            return {"message_id": msg_id, "conversation_id": conversation_id}
        except ValueError as e: raise ToolError(str(e))

    @mcp.tool(annotations={"readOnlyHint": True})
    def export_conversation(
        id: Annotated[str, Field(description="Conversation ID")],
        format: Annotated[str, Field(description="Export format: markdown or json")] = "markdown",
        path_index: Annotated[int | None, Field(description="Export specific path")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> str:
        """Export a conversation as markdown or JSON."""
        database = _get_db(ctx, db) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        conv = database.load_conversation(id)
        if conv is None: raise ToolError(f"Conversation not found: {id}")
        if format == "json":
            return json.dumps({"id": conv.id, "title": conv.title,
                "messages": [{"id": m.id, "role": m.role, "content": m.content, "parent_id": m.parent_id}
                             for m in conv.messages.values()]}, indent=2)
        # Default: markdown
        paths = conv.get_all_paths()
        if path_index is not None:
            if path_index < 0 or path_index >= len(paths): raise ToolError(f"Path index out of range: {path_index}")
            paths = [paths[path_index]]
        lines = [f"# {conv.title or conv.id}\n"]
        for i, path in enumerate(paths):
            if len(paths) > 1: lines.append(f"\n## Path {i}\n")
            for msg in path:
                lines.append(f"**{msg.role}**: {msg.get_text()}\n")
        return "\n".join(lines)
```

Add `from memex.models import Message` to the imports at the top of `server.py`.

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/server.py tests/memex/test_server.py
git commit -m "feat(memex): all 7 MCP tools (query, paths, update, append, export)"
```

---

## Task 12: MCP Server — Resources

**Files:**
- Modify: `memex/server.py`
- Modify: `tests/memex/test_server.py`

**Step 1: Write failing tests**

```python
class TestResources:
    def test_schema_resource(self, db):
        schema = db.get_schema()
        assert "CREATE TABLE conversations" in schema

    def test_statistics_in_databases(self, db):
        stats = db.get_statistics()
        assert stats["total_conversations"] == 1

    def test_conversation_resource(self, db):
        conv = db.load_conversation("c1")
        assert conv is not None
        paths = db.list_paths("c1")
        assert len(paths) >= 1
```

**Step 2: Run** → PASS (tests db methods)

**Step 3: Add resources to `_register_resources` in `memex/server.py`**

```python
def _register_resources(mcp: FastMCP):

    @mcp.resource("memex://schema")
    def schema_resource(ctx: Context = None) -> str:
        """Database schema — tables, columns, types, indexes."""
        db = _get_db(ctx) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        return db.get_schema()

    @mcp.resource("memex://databases")
    def databases_resource(ctx: Context = None) -> str:
        """Registered databases with statistics."""
        if ctx and hasattr(ctx, 'lifespan_context'):
            registry = _get_registry(ctx)
            result = {}
            for name, db in registry.all_dbs().items():
                result[name] = db.get_statistics()
                result[name]["primary"] = (name == registry.primary)
            return json.dumps(result, indent=2)
        else:
            stats = mcp._test_db.get_statistics()
            stats["primary"] = True
            return json.dumps({"default": stats}, indent=2)

    @mcp.resource("memex://conversations/{conv_id}")
    def conversation_resource(conv_id: str, ctx: Context = None) -> str:
        """Conversation metadata and path listing."""
        db = _get_db(ctx) if ctx and hasattr(ctx, 'lifespan_context') else mcp._test_db
        conv = db.load_conversation(conv_id)
        if conv is None: return json.dumps({"error": f"Not found: {conv_id}"})
        paths = db.list_paths(conv_id)
        return json.dumps({
            "id": conv.id, "title": conv.title, "source": conv.source,
            "model": conv.model, "summary": conv.summary,
            "message_count": conv.message_count, "tags": conv.tags,
            "created_at": str(conv.created_at), "updated_at": str(conv.updated_at),
            "starred": conv.starred_at is not None,
            "pinned": conv.pinned_at is not None,
            "archived": conv.archived_at is not None,
            "sensitive": conv.sensitive,
            "metadata": conv.metadata,
            "paths": paths,
        }, indent=2)
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/server.py tests/memex/test_server.py
git commit -m "feat(memex): 3 MCP resources (schema, databases, conversations)"
```

---

## Task 13: Importers — OpenAI, Anthropic, Gemini

**Files:**
- Create: `memex/importers/__init__.py`
- Create: `memex/importers/openai.py`
- Create: `memex/importers/anthropic.py`
- Create: `memex/importers/gemini.py`
- Create: `tests/memex/test_importers.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_importers.py
import json
from memex.importers.openai import detect, import_file

class TestOpenAIImporter:
    def test_detect_valid(self, tmp_path):
        f = tmp_path / "export.json"
        f.write_text(json.dumps([{"id": "conv1", "mapping": {"node1": {"message": {"content": {"parts": ["hi"]}}}}}]))
        assert detect(str(f)) is True

    def test_detect_invalid(self, tmp_path):
        f = tmp_path / "other.json"
        f.write_text(json.dumps({"not": "openai"}))
        assert detect(str(f)) is False

    def test_import_simple(self, tmp_path):
        data = [{"id": "conv1", "title": "Test", "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {
                "root": {"id": "root", "children": ["m1"], "message": None},
                "m1": {"id": "m1", "parent": "root", "children": ["m2"],
                    "message": {"id": "m1", "author": {"role": "user"}, "content": {"parts": ["hello"]}, "create_time": 1700000000}},
                "m2": {"id": "m2", "parent": "m1", "children": [],
                    "message": {"id": "m2", "author": {"role": "assistant"}, "content": {"parts": ["hi"]}, "create_time": 1700000001, "metadata": {"model_slug": "gpt-4"}}},
        }}]
        f = tmp_path / "export.json"
        f.write_text(json.dumps(data))
        convs = import_file(str(f))
        assert len(convs) == 1
        assert convs[0].title == "Test"
        assert convs[0].source == "openai"
        assert len(convs[0].messages) >= 2
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement OpenAI importer**

```python
# memex/importers/__init__.py
"""Convention-based importers. Each module provides detect() and import_file()."""

# memex/importers/openai.py
"""Import OpenAI conversation exports (conversations.json)."""
import json
from datetime import datetime
from typing import List, Optional
from memex.models import Conversation, Message, text_block, media_block, tool_use_block, tool_result_block

def detect(path: str) -> bool:
    try:
        with open(path) as f: data = json.load(f)
        if isinstance(data, list) and data and "mapping" in data[0]: return True
        return False
    except (json.JSONDecodeError, IOError, KeyError, IndexError): return False

def import_file(path: str) -> List[Conversation]:
    with open(path) as f: data = json.load(f)
    if not isinstance(data, list): data = [data]
    conversations = []
    for item in data:
        conv = _import_conversation(item)
        if conv: conversations.append(conv)
    return conversations

def _import_conversation(data: dict) -> Optional[Conversation]:
    conv_id = data.get("id") or data.get("conversation_id", "")
    mapping = data.get("mapping", {})
    if not mapping: return None
    created = datetime.fromtimestamp(data["create_time"]) if data.get("create_time") else datetime.now()
    updated = datetime.fromtimestamp(data["update_time"]) if data.get("update_time") else created
    conv = Conversation(id=conv_id, title=data.get("title"), source="openai",
        created_at=created, updated_at=updated)
    model = None
    for node_id, node in mapping.items():
        msg_data = node.get("message")
        if not msg_data: continue
        role = msg_data.get("author", {}).get("role", "unknown")
        if role in ("system",) and not msg_data.get("content", {}).get("parts"): continue
        parts = msg_data.get("content", {}).get("parts", [])
        content = []
        for part in parts:
            if isinstance(part, str): content.append(text_block(part))
            elif isinstance(part, dict):
                if "asset_pointer" in part: content.append(media_block("image/png", url=part.get("asset_pointer", "")))
                elif part.get("content_type") == "image_asset_pointer": content.append(media_block("image/png", url=part.get("asset_pointer", "")))
                else: content.append(text_block(str(part)))
        if not content: content = [text_block("")]
        msg_model = msg_data.get("metadata", {}).get("model_slug")
        if msg_model and role == "assistant": model = msg_model
        parent_id = node.get("parent")
        if parent_id and parent_id not in mapping: parent_id = None
        if parent_id and mapping.get(parent_id, {}).get("message") is None:
            parent_id = None  # Skip virtual root nodes
        msg = Message(id=node_id, role=role, content=content, parent_id=parent_id, model=msg_model,
            created_at=datetime.fromtimestamp(msg_data["create_time"]) if msg_data.get("create_time") else None)
        conv.add_message(msg)
    conv.model = model
    return conv
```

**Step 4: Run tests** → PASS

**Step 5: Create Anthropic and Gemini importers** (similar pattern, adapted for their formats)

The Anthropic and Gemini importers follow the same `detect()` + `import_file()` contract.
Reference CTK's `ctk/integrations/importers/anthropic.py` and `gemini.py` for format details.
Adapt to use memex content blocks instead of CTK's `MessageContent` class.

**Step 6: Commit**

```bash
git add memex/importers/ tests/memex/test_importers.py
git commit -m "feat(memex): OpenAI, Anthropic, Gemini importers"
```

---

## Task 14: Exporters — Markdown and JSON

**Files:**
- Create: `memex/exporters/__init__.py`
- Create: `memex/exporters/markdown.py`
- Create: `memex/exporters/json_export.py`
- Create: `tests/memex/test_exporters.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_exporters.py
from datetime import datetime
from memex.models import Conversation, Message, text_block
from memex.exporters.markdown import export
from memex.exporters.json_export import export as json_export

def _conv():
    now = datetime.now()
    conv = Conversation(id="c1", created_at=now, updated_at=now, title="Test")
    conv.add_message(Message(id="m1", role="user", content=[text_block("hello")]))
    conv.add_message(Message(id="m2", role="assistant", content=[text_block("hi")], parent_id="m1"))
    return conv

class TestMarkdownExporter:
    def test_export_single(self, tmp_path):
        out = tmp_path / "out.md"
        export([_conv()], str(out))
        content = out.read_text()
        assert "# Test" in content
        assert "hello" in content
        assert "hi" in content

class TestJSONExporter:
    def test_export_single(self, tmp_path):
        out = tmp_path / "out.json"
        json_export([_conv()], str(out))
        import json
        data = json.loads(out.read_text())
        assert isinstance(data, list)
        assert data[0]["id"] == "c1"
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement exporters**

```python
# memex/exporters/__init__.py
"""Convention-based exporters. Each module provides export()."""

# memex/exporters/markdown.py
"""Export conversations as Markdown."""
from memex.models import Conversation
from typing import List

def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    lines = []
    for conv in conversations:
        lines.append(f"# {conv.title or conv.id}\n")
        if conv.source: lines.append(f"*Source: {conv.source}*\n")
        for path_msgs in conv.get_all_paths():
            for msg in path_msgs:
                text = msg.get_text()
                lines.append(f"**{msg.role}**: {text}\n")
            lines.append("---\n")
    with open(path, "w") as f: f.write("\n".join(lines))

# memex/exporters/json_export.py
"""Export conversations as JSON."""
import json
from memex.models import Conversation
from typing import List

def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    data = []
    for conv in conversations:
        data.append({
            "id": conv.id, "title": conv.title, "source": conv.source,
            "model": conv.model, "tags": conv.tags,
            "created_at": str(conv.created_at), "updated_at": str(conv.updated_at),
            "messages": [{"id": m.id, "role": m.role, "content": m.content,
                "parent_id": m.parent_id, "model": m.model}
                for m in conv.messages.values()],
        })
    with open(path, "w") as f: json.dump(data, f, indent=2)
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/exporters/ tests/memex/test_exporters.py
git commit -m "feat(memex): Markdown and JSON exporters"
```

---

## Task 15: CLI — Import, Export, Serve

**Files:**
- Create: `memex/cli.py`
- Create: `tests/memex/test_cli.py`

**Step 1: Write failing tests**

```python
# tests/memex/test_cli.py
import json, subprocess, sys

class TestCLI:
    def test_version(self):
        result = subprocess.run([sys.executable, "-m", "memex", "--version"], capture_output=True, text=True)
        assert "0.1.0" in result.stdout

    def test_import_openai(self, tmp_path):
        db_dir = tmp_path / "db"
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps([{
            "id": "c1", "title": "Test", "create_time": 1700000000, "update_time": 1700000001,
            "mapping": {"m1": {"id": "m1", "parent": None, "children": [],
                "message": {"id": "m1", "author": {"role": "user"}, "content": {"parts": ["hello"]}, "create_time": 1700000000}}},
        }]))
        result = subprocess.run([sys.executable, "-m", "memex", "import", str(export_file), "--db", str(db_dir)],
            capture_output=True, text=True)
        assert result.returncode == 0
```

**Step 2: Run to verify failure** → FAIL

**Step 3: Implement `memex/cli.py`**

```python
"""Thin CLI for memex. Delegates to core for all logic."""
from __future__ import annotations
import argparse, importlib, os, sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(prog="memex", description="Personal conversation knowledge base")
    parser.add_argument("--version", action="version", version=f"memex {_get_version()}")
    sub = parser.add_subparsers(dest="command")

    # import
    imp = sub.add_parser("import", help="Import conversations")
    imp.add_argument("file", help="File to import")
    imp.add_argument("--format", help="Force importer format")
    imp.add_argument("--db", help="Database directory", default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"))

    # export
    exp = sub.add_parser("export", help="Export conversations")
    exp.add_argument("output", help="Output file path")
    exp.add_argument("--format", default="markdown", help="Export format")
    exp.add_argument("--db", help="Database directory", default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"))

    # serve
    srv = sub.add_parser("serve", help="Start MCP server")

    args = parser.parse_args()
    if args.command == "import": _cmd_import(args)
    elif args.command == "export": _cmd_export(args)
    elif args.command == "serve": _cmd_serve(args)
    else: parser.print_help()

def _get_version():
    from memex import __version__; return __version__

def _cmd_import(args):
    from memex.db import Database
    db_path = os.path.expanduser(args.db)
    db = Database(db_path)
    convs = _auto_import(args.file, args.format)
    for conv in convs: db.save_conversation(conv)
    print(f"Imported {len(convs)} conversation(s) into {db_path}")
    db.close()

def _auto_import(file_path, format_name=None):
    importers_dir = Path(__file__).parent / "importers"
    # User overrides first
    user_dir = Path.home() / ".memex" / "importers"
    for d in [user_dir, importers_dir]:
        if not d.exists(): continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"): continue
            if format_name and py_file.stem != format_name: continue
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "detect") and hasattr(mod, "import_file"):
                if format_name or mod.detect(file_path):
                    return mod.import_file(file_path)
    print(f"No importer found for {file_path}", file=sys.stderr)
    return []

def _cmd_export(args):
    from memex.db import Database
    db = Database(os.path.expanduser(args.db))
    result = db.query_conversations(limit=10000)
    convs = [db.load_conversation(item["id"]) for item in result["items"]]
    convs = [c for c in convs if c is not None]
    # Find exporter
    exporters_dir = Path(__file__).parent / "exporters"
    for py_file in exporters_dir.glob("*.py"):
        if py_file.name.startswith("_"): continue
        if py_file.stem == args.format or py_file.stem == f"{args.format}_export":
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            if hasattr(mod, "export"):
                mod.export(convs, args.output); print(f"Exported {len(convs)} conversation(s)"); return
    print(f"Unknown export format: {args.format}", file=sys.stderr)

def _cmd_serve(args):
    from memex.server import main as serve_main; serve_main()

if __name__ == "__main__": main()
```

**Step 4: Run tests** → all PASS

**Step 5: Commit**

```bash
git add memex/cli.py tests/memex/test_cli.py
git commit -m "feat(memex): CLI with import, export, and serve commands"
```

---

## Task 16: Integration Test — Import → Search → Export Roundtrip

**Files:**
- Create: `tests/memex/test_integration.py`

**Step 1: Write integration test**

```python
# tests/memex/test_integration.py
"""End-to-end: import OpenAI export → search → update → export."""
import json
from datetime import datetime
from memex.db import Database
from memex.models import Conversation, Message, text_block

class TestRoundtrip:
    def test_full_workflow(self, tmp_db_path):
        db = Database(tmp_db_path)

        # 1. Create and save conversations
        for i in range(3):
            now = datetime(2024, 6, i+1)
            conv = Conversation(id=f"conv{i}", created_at=now, updated_at=now,
                title=f"Python discussion {i}", source="openai", model="gpt-4",
                tags=["python", "coding"])
            conv.add_message(Message(id="m1", role="user", content=[text_block(f"Tell me about Python topic {i}")]))
            conv.add_message(Message(id="m2", role="assistant",
                content=[text_block(f"Python topic {i} is fascinating because...")], parent_id="m1"))
            db.save_conversation(conv)

        # 2. Search
        result = db.query_conversations(query="Python topic 1")
        assert len(result["items"]) >= 1

        # 3. Update (star + tag + metadata)
        db.update_conversation("conv0", starred=True, add_tags=["important"],
            metadata={"reviewed_by": "test"})
        conv0 = db.load_conversation("conv0")
        assert conv0.starred_at is not None
        assert "important" in conv0.tags
        assert conv0.metadata["reviewed_by"] == "test"

        # 4. Append message
        db.append_message("conv0", Message(id="m3", role="user",
            content=[text_block("Follow-up question")], parent_id="m2"))
        conv0 = db.load_conversation("conv0")
        assert conv0.message_count == 3

        # 5. Path navigation
        paths = db.list_paths("conv0")
        assert len(paths) == 1
        assert paths[0]["message_count"] == 3
        messages = db.get_path_messages("conv0", path_index=0)
        assert len(messages) == 3

        # 6. SQL query
        rows = db.execute_sql("SELECT id, title FROM conversations WHERE starred_at IS NOT NULL")
        assert len(rows) == 1 and rows[0]["id"] == "conv0"

        # 7. Statistics
        stats = db.get_statistics()
        assert stats["total_conversations"] == 3
        assert stats["total_messages"] == 7  # 3*2 + 1 appended

        # 8. Export
        from memex.exporters.markdown import export as md_export
        from memex.exporters.json_export import export as json_export
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            md_export([conv0], os.path.join(td, "out.md"))
            json_export([conv0], os.path.join(td, "out.json"))
            assert os.path.exists(os.path.join(td, "out.md"))
            data = json.loads(open(os.path.join(td, "out.json")).read())
            assert data[0]["id"] == "conv0"

        db.close()
```

**Step 2: Run integration test**

Run: `pytest tests/memex/test_integration.py -v`
Expected: PASS

**Step 3: Run full test suite with coverage**

Run: `pytest tests/memex/ -v --cov=memex --cov-report=term-missing`

**Step 4: Commit**

```bash
git add tests/memex/test_integration.py
git commit -m "test(memex): integration test for full import→search→update→export workflow"
```

---

## Summary

| Task | Component | Files | Tests |
|------|-----------|-------|-------|
| 1 | Scaffolding | 5 created | 0 |
| 2 | Content blocks | `models.py` | ~10 |
| 3 | Message + Conversation | `models.py` | ~15 |
| 4 | DB schema + connection | `db.py` | ~8 |
| 5 | DB save/load | `db.py` | ~8 |
| 6 | DB search/query | `db.py` | ~9 |
| 7 | DB update/append | `db.py` | ~8 |
| 8 | DB stats/paths | `db.py` | ~7 |
| 9 | Config + registry | `config.py` | ~8 |
| 10 | Server + SQL tool | `server.py` | ~3 |
| 11 | All 7 tools | `server.py` | ~5 |
| 12 | 3 resources | `server.py` | ~3 |
| 13 | Importers | `importers/` | ~5 |
| 14 | Exporters | `exporters/` | ~3 |
| 15 | CLI | `cli.py` | ~2 |
| 16 | Integration | `test_integration.py` | 1 |
| **Total** | **7 files + importers/exporters** | | **~95 tests** |
