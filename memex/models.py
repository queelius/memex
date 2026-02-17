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
