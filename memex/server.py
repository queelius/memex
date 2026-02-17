"""Memex MCP server -- the primary interface."""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any, Optional

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
        mcp._test_db = db
        mcp._test_sql_write = sql_write
    _register_tools(mcp)
    _register_resources(mcp)
    return mcp


def _get_registry(ctx: Context) -> DatabaseRegistry:
    """Get the DatabaseRegistry from the lifespan context."""
    return ctx.request_context.lifespan_context["registry"]


def _get_db_from_ctx(mcp, ctx, db_name=None):
    """Get database from either lifespan context or test injection."""
    if (ctx is not None
            and hasattr(ctx, 'request_context')
            and ctx.request_context is not None
            and hasattr(ctx.request_context, 'lifespan_context')
            and ctx.request_context.lifespan_context is not None):
        return _get_registry(ctx).get_db(db_name)
    return mcp._test_db


def _get_sql_write(mcp, ctx):
    """Get sql_write setting from either lifespan context or test injection."""
    if (ctx is not None
            and hasattr(ctx, 'request_context')
            and ctx.request_context is not None
            and hasattr(ctx.request_context, 'lifespan_context')
            and ctx.request_context.lifespan_context is not None):
        return _get_registry(ctx).sql_write
    return getattr(mcp, '_test_sql_write', False)


def _register_tools(mcp: FastMCP):
    """Register all MCP tools on the server."""

    @mcp.tool(annotations={"readOnlyHint": True})
    def execute_sql(
        sql: Annotated[str, Field(description="SQL query to execute")],
        db: Annotated[str | None, Field(description="Target database name")] = None,
        ctx: Context = None,
    ) -> list[dict]:
        """Run a SQL query against the database. Read-only by default."""
        database = _get_db_from_ctx(mcp, ctx, db)
        sql_write = _get_sql_write(mcp, ctx)
        sql_stripped = sql.strip().upper()
        if not sql_write and not (sql_stripped.startswith("SELECT") or sql_stripped.startswith("PRAGMA")):
            raise ToolError("SQL writes are disabled. Set MEMEX_SQL_WRITE=true to enable.")
        try:
            return database.execute_sql(sql)
        except Exception as e:
            raise ToolError(str(e))

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
        database = _get_db_from_ctx(mcp, ctx, db)
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
        database = _get_db_from_ctx(mcp, ctx, db)
        try:
            return database.list_paths(id)
        except ValueError as e:
            raise ToolError(str(e))

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
        database = _get_db_from_ctx(mcp, ctx, db)
        try:
            return database.get_path_messages(
                id, path_index=path_index, leaf_message_id=leaf_message_id,
                offset=offset, limit=limit,
            )
        except ValueError as e:
            raise ToolError(str(e))

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
        database = _get_db_from_ctx(mcp, ctx, db)
        try:
            database.update_conversation(
                id, title=title, summary=summary, starred=starred,
                pinned=pinned, archived=archived, sensitive=sensitive,
                add_tags=add_tags, remove_tags=remove_tags, metadata=metadata,
            )
            return {"updated": id}
        except ValueError as e:
            raise ToolError(str(e))

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
        """Add a message to the conversation tree."""
        database = _get_db_from_ctx(mcp, ctx, db)
        msg_id = str(uuid.uuid4())[:8]
        msg = Message(
            id=msg_id, role=role, content=content,
            parent_id=parent_message_id, model=message_model,
        )
        try:
            database.append_message(conversation_id, msg)
            return {"message_id": msg_id, "conversation_id": conversation_id}
        except ValueError as e:
            raise ToolError(str(e))

    @mcp.tool(annotations={"readOnlyHint": True})
    def export_conversation(
        id: Annotated[str, Field(description="Conversation ID")],
        format: Annotated[str, Field(description="Export format: markdown or json")] = "markdown",
        path_index: Annotated[int | None, Field(description="Export specific path")] = None,
        db: Annotated[str | None, Field(description="Target database")] = None,
        ctx: Context = None,
    ) -> str:
        """Export a conversation as markdown or JSON."""
        database = _get_db_from_ctx(mcp, ctx, db)
        conv = database.load_conversation(id)
        if conv is None:
            raise ToolError(f"Conversation not found: {id}")

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

        # Default: markdown
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
        if (ctx is not None
                and hasattr(ctx, 'request_context')
                and ctx.request_context is not None
                and hasattr(ctx.request_context, 'lifespan_context')
                and ctx.request_context.lifespan_context is not None):
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
        db = _get_db_from_ctx(mcp, ctx)
        conv = db.load_conversation(conv_id)
        if conv is None:
            return json.dumps({"error": f"Not found: {conv_id}"})
        paths = db.list_paths(conv_id)
        return json.dumps({
            "id": conv.id,
            "title": conv.title,
            "source": conv.source,
            "model": conv.model,
            "summary": conv.summary,
            "message_count": conv.message_count,
            "tags": conv.tags,
            "created_at": str(conv.created_at),
            "updated_at": str(conv.updated_at),
            "starred": conv.starred_at is not None,
            "pinned": conv.pinned_at is not None,
            "archived": conv.archived_at is not None,
            "sensitive": conv.sensitive,
            "metadata": conv.metadata,
            "paths": paths,
        }, indent=2)


def main():
    """Entry point for `memex serve`."""
    mcp = FastMCP("memex", lifespan=lifespan)
    _register_tools(mcp)
    _register_resources(mcp)
    mcp.run()
