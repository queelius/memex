"""Thin CLI for memex. Delegates to core for all logic."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="memex", description="Personal conversation knowledge base"
    )
    parser.add_argument(
        "--version", action="version", version=f"memex {_get_version()}"
    )
    sub = parser.add_subparsers(dest="command")

    # import
    imp = sub.add_parser("import", help="Import conversations from a file")
    imp.add_argument("file", help="File to import")
    imp.add_argument("--format", help="Force importer format (e.g. openai, anthropic, gemini)")
    imp.add_argument("--no-copy-assets", action="store_true",
                     help="Skip copying media assets into the database directory")
    imp.add_argument(
        "--db",
        help="Database directory",
        default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"),
    )

    # export
    exp = sub.add_parser("export", help="Export conversations")
    exp.add_argument("output", help="Output file path")
    exp.add_argument("--format", default="markdown", help="Export format (markdown, json)")
    exp.add_argument(
        "--db",
        help="Database directory",
        default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"),
    )

    # show
    show = sub.add_parser("show", help="Display a conversation")
    show.add_argument("id", nargs="?", help="Conversation ID (omit to list all)")
    show.add_argument("--raw", action="store_true", help="(deprecated, now always prints markdown)")
    show.add_argument(
        "--db",
        help="Database directory",
        default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"),
    )

    # mcp
    sub.add_parser("mcp", help="Start MCP server")

    # run
    run_p = sub.add_parser("run", help="Run a memex script")
    run_p.add_argument("name", nargs="?", help="Script name (omit or use --list to list)")
    run_p.add_argument("--list", action="store_true", help="List available scripts")
    run_p.add_argument("--apply", action="store_true", help="Commit changes (default: dry-run)")
    run_p.add_argument("--verbose", action="store_true", help="Verbose output")
    run_p.add_argument(
        "--db",
        help="Database directory",
        default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"),
    )

    args, remaining = parser.parse_known_args()
    if args.command == "import":
        _cmd_import(args)
    elif args.command == "show":
        _cmd_show(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "mcp":
        _cmd_mcp(args)
    elif args.command == "run":
        _cmd_run(args, remaining)
    else:
        parser.print_help()


def _get_version():
    from memex import __version__

    return __version__


def _cmd_import(args):
    from memex.db import Database
    from memex.assets import resolve_source_assets, copy_assets

    db_path = os.path.expanduser(args.db)
    source_dir = Path(args.file).resolve().parent
    asset_dir = Path(db_path) / "assets"
    with Database(db_path) as db:
        convs = _auto_import(args.file, args.format)
        for conv in convs:
            # Extract provenance before save (pop to keep metadata clean)
            prov = conv.metadata.pop("_provenance", None)
            # Resolve and copy media assets
            if not args.no_copy_assets:
                source_type = prov.get("source_type", "") if prov else ""
                resolve_source_assets(conv, source_dir, source_type)
                copy_assets(conv, asset_dir)
            db.save_conversation(conv)
            # Write provenance after save (CASCADE-safe ordering)
            if prov:
                db.save_provenance(
                    conv.id,
                    source_type=prov.get("source_type", "unknown"),
                    source_file=prov.get("source_file"),
                    source_id=prov.get("source_id"),
                    source_hash=prov.get("source_hash"),
                )
        print(f"Imported {len(convs)} conversation(s) into {db_path}")


def _auto_import(file_path, format_name=None):
    """Auto-detect importer and import file.

    Search order: built-in importers first, then user importers (~/.memex/importers/).
    Warns if a user plugin shadows a built-in name.
    """
    importers_dir = Path(__file__).parent / "importers"
    user_dir = Path.home() / ".memex" / "importers"

    # Collect built-in importer names for shadow detection
    builtin_names = set()
    if importers_dir.exists():
        for py_file in importers_dir.glob("*.py"):
            if not py_file.name.startswith("_"):
                builtin_names.add(py_file.stem)

    # Warn about shadows in user directory
    if user_dir.exists():
        for py_file in user_dir.glob("*.py"):
            if not py_file.name.startswith("_") and py_file.stem in builtin_names:
                print(
                    f"Warning: user importer '{py_file.stem}' shadows built-in. "
                    f"Rename to avoid conflicts, or use --format to select explicitly.",
                    file=sys.stderr,
                )

    # Search built-ins first, then user importers
    for d in [importers_dir, user_dir]:
        if not d.exists():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            if format_name and py_file.stem != format_name:
                continue
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "detect") and hasattr(mod, "import_file"):
                if format_name or mod.detect(file_path):
                    return mod.import_file(file_path)
    print(f"Error: no importer found for {file_path}", file=sys.stderr)
    sys.exit(1)


def _cmd_show(args):
    from memex.db import Database

    db_path = os.path.expanduser(args.db)
    with Database(db_path, readonly=True) as db:
        if args.id is None:
            # List mode
            cursor = None
            while True:
                result = db.query_conversations(limit=50, cursor=cursor)
                for item in result["items"]:
                    tags = f"  [{item['tags_csv']}]" if item.get("tags_csv") else ""
                    print(f"{item['id']}  {item['message_count']:3d} msgs  {item['title'] or '(untitled)'}{tags}")
                if not result["has_more"]:
                    break
                cursor = result["next_cursor"]
            return

        conv = db.load_conversation(args.id)
        if conv is None:
            print(f"Error: conversation '{args.id}' not found", file=sys.stderr)
            sys.exit(1)

        print(_render_conversation_md(conv))


def _render_conversation_md(conv):
    """Render a conversation as markdown text."""
    lines = []
    lines.append(f"# {conv.title or conv.id}")
    lines.append("")
    meta = []
    if conv.source:
        meta.append(f"**Source:** {conv.source}")
    if conv.model:
        meta.append(f"**Model:** {conv.model}")
    if conv.tags:
        meta.append(f"**Tags:** {', '.join(conv.tags)}")
    if conv.message_count:
        meta.append(f"**Messages:** {conv.message_count}")
    if meta:
        lines.append(" | ".join(meta))
        lines.append("")
    lines.append("---")
    lines.append("")

    for i, path_msgs in enumerate(conv.get_all_paths()):
        if i > 0:
            lines.append("---")
            lines.append("")
        for msg in path_msgs:
            text = msg.get_content_md()
            lines.append(f"### {msg.role}")
            lines.append("")
            lines.append(text)
            lines.append("")

    return "\n".join(lines)


def _cmd_export(args):
    from memex.db import Database

    with Database(os.path.expanduser(args.db)) as db:
        # Find exporter module first
        exporter_mod = _find_exporter(args.format)
        if exporter_mod is None:
            print(f"Unknown export format: {args.format}", file=sys.stderr)
            sys.exit(1)
        # Load conversations in chunks to avoid memory exhaustion
        convs = []
        cursor = None
        while True:
            result = db.query_conversations(limit=100, cursor=cursor)
            for item in result["items"]:
                conv = db.load_conversation(item["id"])
                if conv is not None:
                    convs.append(conv)
            if not result["has_more"]:
                break
            cursor = result["next_cursor"]
        exporter_mod.export(convs, args.output, db_path=db.db_path)
        print(f"Exported {len(convs)} conversation(s) to {args.output}")


def _find_exporter(format_name):
    """Find an exporter module by format name."""
    exporters_dir = Path(__file__).parent / "exporters"
    for py_file in exporters_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        if py_file.stem == format_name or py_file.stem == f"{format_name}_export":
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "export"):
                return mod
    return None


def _cmd_run(args, remaining):
    from memex.db import Database
    from memex.scripts import discover_scripts, load_script

    if args.list or not args.name:
        scripts = discover_scripts()
        if not scripts:
            print("No scripts available.")
            return
        print("Available scripts:\n")
        for name, info in sorted(scripts.items()):
            print(f"  {name:20s}  {info['description']}")
        print(f"\nUsage: memex run <name> [--apply] [script args...]")
        return

    try:
        mod = load_script(args.name)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Build a sub-parser for the script's own arguments
    script_parser = argparse.ArgumentParser(prog=f"memex run {args.name}")
    mod.register_args(script_parser)
    script_args = script_parser.parse_args(remaining)

    db_path = os.path.expanduser(args.db)
    with Database(db_path, readonly=not args.apply) as db:
        result = mod.run(db, script_args, apply=args.apply)
        if args.verbose and result:
            print(f"\nResult: {result}")


def _cmd_mcp(args):
    from memex.mcp import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    main()
