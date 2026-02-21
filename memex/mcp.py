"""Memex MCP server -- the primary interface."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memex.config import load_config, DatabaseRegistry
from memex.models import Message


@asynccontextmanager
async def lifespan(server):
    """Initialize database registry from config on server startup."""
    import os
    config_path = os.environ.get("MEMEX_CONFIG")
    config = load_config(config_path)
    registry = DatabaseRegistry(config)
    try:
        yield {"registry": registry}
    finally:
        registry.close()


def create_server(db=None, sql_write=False):
    """Create the MCP server.

    Pass db for testing (skips lifespan and uses injected database).
    """
    mcp = FastMCP("memex", lifespan=lifespan if db is None else None)
    if db is not None:
        # Enforce readonly at the SQLite level when sql_write is disabled
        if not sql_write and not db.readonly:
            db.conn.execute("PRAGMA query_only=ON")
            db.readonly = True
        mcp._test_db = db
        mcp._test_sql_write = sql_write
    _register_tools(mcp)
    _register_resources(mcp)
    return mcp


def _has_lifespan_ctx(ctx) -> bool:
    """Check whether a real lifespan context is available (vs test injection)."""
    return (ctx is not None
            and hasattr(ctx, 'request_context')
            and ctx.request_context is not None
            and hasattr(ctx.request_context, 'lifespan_context')
            and ctx.request_context.lifespan_context is not None)


def _get_registry(ctx: Context) -> DatabaseRegistry:
    """Get the DatabaseRegistry from the lifespan context."""
    return ctx.request_context.lifespan_context["registry"]


def _get_db_from_ctx(mcp, ctx, db_name=None):
    """Get database from either lifespan context or test injection."""
    if _has_lifespan_ctx(ctx):
        return _get_registry(ctx).get_db(db_name)
    return mcp._test_db


def _get_sql_write(mcp, ctx):
    """Check sql_write setting for informational error messages."""
    if _has_lifespan_ctx(ctx):
        return _get_registry(ctx).sql_write
    return getattr(mcp, '_test_sql_write', False)


def _conv_metadata(conv, db) -> dict:
    """Build conversation metadata dict with boolean flags, tags, enrichments, provenance."""
    from memex.db import _fmt_dt
    tags = [
        t["tag"]
        for t in db.execute_sql(
            "SELECT tag FROM tags WHERE conversation_id=?", (conv.id,)
        )
    ]
    return {
        "id": conv.id,
        "title": conv.title,
        "source": conv.source,
        "model": conv.model,
        "summary": conv.summary,
        "message_count": conv.message_count,
        "created_at": _fmt_dt(conv.created_at),
        "updated_at": _fmt_dt(conv.updated_at),
        "starred": conv.starred_at is not None,
        "pinned": conv.pinned_at is not None,
        "archived": conv.archived_at is not None,
        "sensitive": conv.sensitive,
        "tags": tags,
        "metadata": conv.metadata,
        "enrichments": db.get_enrichments(conv.id),
        "provenance": db.get_provenance(conv.id),
    }


def _register_tools(mcp: FastMCP):
    """Register all MCP tools on the server."""

    @mcp.tool(annotations={"readOnlyHint": True})
    def execute_sql(
        sql: Annotated[str, Field(description="SQL query to execute")],
        params: Annotated[list | None, Field(description="Query parameters for ? placeholders")] = None,
        db: Annotated[str | None, Field(description="Target database name")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Run a SQL query against the database. Read-only by default (enforced by SQLite PRAGMA query_only)."""
        database = _get_db_from_ctx(mcp, ctx, db)
        try:
            return database.execute_sql(sql, tuple(params) if params else ())
        except sqlite3.OperationalError as e:
            if "attempt to write a readonly database" in str(e):
                raise ToolError("SQL writes are disabled. Set MEMEX_SQL_WRITE=true to enable.")
            raise ToolError(str(e))
        except Exception as e:
            raise ToolError(str(e))

    @mcp.tool(annotations={"readOnlyHint": True})
    def query_conversations(
        query: Annotated[str | None, Field(description="FTS5 search text")] = None,
        title: Annotated[str | None, Field(description="LIKE substring match on title")] = None,
        starred: Annotated[bool | None, Field(description="Filter by starred")] = None,
        pinned: Annotated[bool | None, Field(description="Filter by pinned")] = None,
        archived: Annotated[bool | None, Field(description="Filter by archived")] = None,
        sensitive: Annotated[bool | None, Field(description="Filter by sensitive")] = None,
        source: Annotated[str | None, Field(description="Filter by source")] = None,
        model: Annotated[str | None, Field(description="Filter by model")] = None,
        tag: Annotated[str | None, Field(description="Filter by tag")] = None,
        before: Annotated[str | None, Field(description="Only conversations created before this date (YYYY-MM-DD)")] = None,
        after: Annotated[str | None, Field(description="Only conversations created after this date (YYYY-MM-DD)")] = None,
        enrichment_type: Annotated[str | None, Field(description="Filter by enrichment type (e.g. topic, summary)")] = None,
        enrichment_value: Annotated[str | None, Field(description="Filter by enrichment value substring")] = None,
        include_paths: Annotated[bool, Field(description="Include path summaries to eliminate follow-up list_paths call")] = False,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Field(description="Pagination cursor")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict:
        """Search and list conversations. FTS5 when query provided, otherwise chronological."""
        database = _get_db_from_ctx(mcp, ctx, db)
        result = database.query_conversations(
            query=query, title=title, starred=starred, pinned=pinned,
            archived=archived, sensitive=sensitive, source=source,
            model=model, tag=tag, before=before, after=after,
            enrichment_type=enrichment_type, enrichment_value=enrichment_value,
            limit=limit, cursor=cursor,
        )
        # Post-process: convert tags_csv to list, timestamps to booleans
        for item in result["items"]:
            csv = item.pop("tags_csv", None)
            item["tags"] = csv.split(",") if csv else []
            item["starred"] = item.pop("starred_at", None) is not None
            item["pinned"] = item.pop("pinned_at", None) is not None
            item["archived"] = item.pop("archived_at", None) is not None
            item["sensitive"] = bool(item.get("sensitive", 0))
        # Optionally inline path summaries
        if include_paths:
            for item in result["items"]:
                try:
                    item["paths"] = database.list_paths(item["id"])
                except ValueError:
                    item["paths"] = []
        return result

    @mcp.tool(annotations={"readOnlyHint": True})
    def get_conversation(
        id: Annotated[str, Field(description="Conversation ID")],
        path_index: Annotated[int | None, Field(description="Path index to read messages from")] = None,
        leaf_message_id: Annotated[str | None, Field(description="Leaf message ID to trace path from")] = None,
        offset: Annotated[int, Field(description="Skip first N messages (only in messages mode)")] = 0,
        limit: Annotated[int | None, Field(description="Max messages to return (only in messages mode)")] = None,
        format: Annotated[str | None, Field(description="Export format: 'markdown' or 'json'. When set, returns formatted string.")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict | str:
        """Get conversation metadata, messages along a path, or export. Three modes:
        - id only → metadata + all path summaries
        - id + path_index/leaf_message_id → messages along that path (with offset/limit)
        - id + format → exported string (markdown or json)
        """
        database = _get_db_from_ctx(mcp, ctx, db)
        conv = database.load_conversation(id)
        if conv is None:
            raise ToolError(f"Conversation not found: {id}")

        # Export mode
        if format is not None:
            if format == "json":
                return json.dumps({
                    "id": conv.id,
                    "title": conv.title,
                    "messages": [
                        {
                            "id": m.id, "role": m.role,
                            "content": m.content, "parent_id": m.parent_id,
                        }
                        for m in conv.messages.values()
                    ],
                }, indent=2)
            # Default export: markdown
            paths = conv.get_all_paths()
            if path_index is not None:
                if path_index < 0 or path_index >= len(paths):
                    raise ToolError(f"Path index out of range: {path_index}")
                paths = [paths[path_index]]
            lines = [f"# {conv.title or conv.id}\n"]
            for i, path in enumerate(paths):
                if len(paths) > 1:
                    lines.append(f"\n## Path {i}\n")
                for msg in path:
                    lines.append(f"**{msg.role}**: {msg.get_text()}\n")
            return "\n".join(lines)

        # Messages mode: path_index or leaf_message_id specified
        if path_index is not None or leaf_message_id is not None:
            try:
                messages = database.get_path_messages(
                    id, path_index=path_index,
                    leaf_message_id=leaf_message_id,
                    offset=offset, limit=limit,
                )
            except ValueError as e:
                raise ToolError(str(e))
            return {
                "conversation": _conv_metadata(conv, database),
                "messages": messages,
            }

        # Metadata mode: id only
        meta = _conv_metadata(conv, database)
        meta["paths"] = database.list_paths(id)
        return meta

    @mcp.tool(annotations={"readOnlyHint": True})
    def search_messages(
        query: Annotated[str, Field(description="Search text")],
        mode: Annotated[str, Field(description="Search mode: 'fts' (token OR), 'phrase' (exact substring), 'like' (SQL LIKE pattern)")] = "fts",
        conversation_id: Annotated[str | None, Field(description="Restrict to one conversation")] = None,
        role: Annotated[str | None, Field(description="Filter by message role")] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 20,
        context_messages: Annotated[int, Field(description="Include N surrounding messages for context", ge=0, le=5)] = 1,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Message-level search with context snippets. Returns matches grouped with conversation metadata."""
        database = _get_db_from_ctx(mcp, ctx, db)
        try:
            matches = database.search_messages(
                query, mode=mode, conversation_id=conversation_id,
                role=role, limit=limit,
            )
        except ValueError as e:
            raise ToolError(str(e))

        results = []
        for match in matches:
            entry = {
                "conversation_id": match["conversation_id"],
                "conversation_title": match["conversation_title"],
                "message_id": match["message_id"],
                "role": match["role"],
                "content": json.loads(match["content"]) if isinstance(match["content"], str) else match["content"],
            }
            if context_messages > 0:
                entry["context"] = database.get_context_messages(
                    match["conversation_id"], match["message_id"],
                    context=context_messages,
                )
                # Parse content JSON in context messages
                for cm in entry["context"]:
                    if isinstance(cm.get("content"), str):
                        cm["content"] = json.loads(cm["content"])
            results.append(entry)
        return results

    @mcp.tool(annotations={"idempotentHint": True})
    def update_conversations(
        ids: Annotated[list[str], Field(description="Conversation IDs to update (1..N)")],
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
        database = _get_db_from_ctx(mcp, ctx, db)
        updated = []
        errors = []
        for cid in ids:
            try:
                database.update_conversation(
                    cid, title=title, summary=summary, starred=starred,
                    pinned=pinned, archived=archived, sensitive=sensitive,
                    add_tags=add_tags, remove_tags=remove_tags,
                    metadata=metadata,
                )
                conv = database.load_conversation(cid)
                updated.append(_conv_metadata(conv, database))
            except ValueError as e:
                errors.append({"id": cid, "error": str(e)})
        return {"updated": updated, "errors": errors}

    @mcp.tool()
    def append_message(
        conversation_id: Annotated[str, Field(description="Conversation ID")],
        role: Annotated[str, Field(description="Message role: user, assistant, system, tool")],
        content: Annotated[list[dict], Field(description="Content blocks array")],
        parent_message_id: Annotated[str | None, Field(description="Parent message ID")] = None,
        message_model: Annotated[str | None, Field(description="Model that generated this message")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> dict:
        """Add a message to the conversation tree. Returns created message and updated conversation metadata."""
        database = _get_db_from_ctx(mcp, ctx, db)
        msg_id = str(uuid.uuid4())
        msg = Message(
            id=msg_id, role=role, content=content,
            parent_id=parent_message_id, model=message_model,
        )
        try:
            database.append_message(conversation_id, msg)
            # Fetch updated conversation metadata for the response
            conv = database.load_conversation(conversation_id)
            return {
                "message_id": msg_id,
                "conversation": _conv_metadata(conv, database),
            }
        except ValueError as e:
            raise ToolError(str(e))

    VALID_ENRICHMENT_TYPES = {"summary", "topic", "importance", "excerpt", "note"}
    VALID_ENRICHMENT_SOURCES = {"user", "claude", "heuristic"}

    @mcp.tool(annotations={"idempotentHint": True})
    def enrich_conversation(
        conversation_id: Annotated[str, Field(description="Conversation ID")],
        enrichments: Annotated[list[dict], Field(description="List of enrichments: [{type, value, source, confidence?}]")],
        db: Annotated[str | None, Field(description="Target database name")] = None,
        ctx: Context = None,
    ) -> dict:
        """Add enrichments (summaries, topics, importance, excerpts, notes) to a conversation. Idempotent -- re-sending the same enrichment updates it."""
        database = _get_db_from_ctx(mcp, ctx, db)
        # Validate conversation exists
        conv = database.load_conversation(conversation_id)
        if conv is None:
            raise ToolError(f"Conversation not found: {conversation_id}")
        # Validate each enrichment
        for e in enrichments:
            if e.get("type") not in VALID_ENRICHMENT_TYPES:
                raise ToolError(
                    f"Invalid enrichment type: {e.get('type')}. "
                    f"Must be one of: {', '.join(sorted(VALID_ENRICHMENT_TYPES))}"
                )
            if e.get("source") not in VALID_ENRICHMENT_SOURCES:
                raise ToolError(
                    f"Invalid enrichment source: {e.get('source')}. "
                    f"Must be one of: {', '.join(sorted(VALID_ENRICHMENT_SOURCES))}"
                )
            conf = e.get("confidence")
            if conf is not None and (conf < 0.0 or conf > 1.0):
                raise ToolError(f"Confidence must be 0.0-1.0, got: {conf}")
        database.save_enrichments(conversation_id, enrichments)
        return {
            "conversation_id": conversation_id,
            "enrichments": database.get_enrichments(conversation_id),
        }

    @mcp.tool(annotations={"readOnlyHint": True})
    def query_enrichments(
        type: Annotated[str | None, Field(description="Filter by enrichment type")] = None,
        value: Annotated[str | None, Field(description="Substring match on value")] = None,
        source: Annotated[str | None, Field(description="Filter by source (user/claude/heuristic)")] = None,
        conversation_id: Annotated[str | None, Field(description="Filter by conversation ID")] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 20,
        db: Annotated[str | None, Field(description="Target database name")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Search enrichments across conversations. Filter by type, value, source, or conversation."""
        database = _get_db_from_ctx(mcp, ctx, db)
        return database.query_enrichments(
            type=type, value=value, source=source,
            conversation_id=conversation_id, limit=limit,
        )


def _register_resources(mcp: FastMCP):
    """Register all MCP resources on the server."""

    @mcp.resource("memex://schema")
    def schema_resource(ctx: Context = None) -> str:
        """Database schema -- tables, columns, types, indexes."""
        db = _get_db_from_ctx(mcp, ctx)
        return db.get_schema()

    @mcp.resource("memex://databases")
    def databases_resource(ctx: Context = None) -> str:
        """Registered databases with statistics."""
        if _has_lifespan_ctx(ctx):
            registry = _get_registry(ctx)
            result = {}
            for name, db in registry.all_dbs().items():
                result[name] = db.get_statistics()
                result[name]["primary"] = (name == registry.primary)
            return json.dumps(result, indent=2)
        stats = mcp._test_db.get_statistics()
        stats["primary"] = True
        return json.dumps({"default": stats}, indent=2)

def main():
    """Entry point for `memex mcp`."""
    create_server().run()
