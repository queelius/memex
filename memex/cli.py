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
    imp.add_argument("file", nargs="?", help="File to import")
    imp.add_argument("--format", help="Force importer format (use --list-formats to see available)")
    imp.add_argument("--list-formats", action="store_true", help="List available import formats")
    imp.add_argument("--no-copy-assets", action="store_true",
                     help="Skip copying media assets into the database directory")
    imp.add_argument(
        "--db",
        help="Database directory",
        default=os.environ.get("MEMEX_DATABASE_PATH", "~/.memex/default"),
    )

    # export
    exp = sub.add_parser("export", help="Export conversations")
    exp.add_argument("output", nargs="?", help="Output file path")
    exp.add_argument("--format", default="markdown", help="Export format (use --list-formats to see available)")
    exp.add_argument("--list-formats", action="store_true", help="List available export formats")
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


def _list_formats(formats, label):
    """Print available formats with descriptions."""
    print(f"Available {label} formats:\n")
    for name, info in sorted(formats.items()):
        print(f"  {name:20s}  {info['description']}")
    print()


def _cmd_import(args):
    if args.list_formats:
        _list_formats(_discover_importers(), "import")
        return
    if args.format:
        importers = _discover_importers()
        if args.format not in importers:
            print(f"Error: unknown format '{args.format}'. "
                  f"Available: {', '.join(sorted(importers))}",
                  file=sys.stderr)
            sys.exit(1)
    if not args.file:
        print("Error: the following arguments are required: file", file=sys.stderr)
        sys.exit(1)

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


def _discover_formats(directory, user_directory, required_attrs, strip_suffix=""):
    """Discover plugin modules from built-in and user directories.

    Returns dict mapping name to {"path": Path, "description": str, "module": mod}.
    User plugins shadow built-in plugins of the same name (with warning).
    strip_suffix removes a naming suffix (e.g. "_export") so json_export.py → "json".
    """
    formats = {}
    builtin_names = set()

    for d in [directory, user_directory]:
        if not d.exists():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            name = py_file.stem
            if strip_suffix and name.endswith(strip_suffix):
                name = name[: -len(strip_suffix)]
            if d == directory:
                builtin_names.add(name)
            elif name in builtin_names:
                print(
                    f"Warning: user plugin '{name}' shadows built-in. "
                    f"Rename to avoid conflicts, or use --format to select explicitly.",
                    file=sys.stderr,
                )
            try:
                spec = importlib.util.spec_from_file_location(name, py_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception:
                continue
            if all(hasattr(mod, a) for a in required_attrs):
                doc = getattr(mod, "__doc__", None) or ""
                formats[name] = {
                    "path": py_file,
                    "description": doc.strip().split("\n")[0].strip(),
                    "module": mod,
                }
    return formats


def _discover_importers():
    return _discover_formats(
        Path(__file__).parent / "importers",
        Path.home() / ".memex" / "importers",
        ("detect", "import_file"),
    )


def _discover_exporters():
    return _discover_formats(
        Path(__file__).parent / "exporters",
        Path.home() / ".memex" / "exporters",
        ("export",),
        strip_suffix="_export",
    )


def _auto_import(file_path, format_name=None):
    """Auto-detect importer and import file."""
    importers = _discover_importers()
    if format_name:
        if format_name not in importers:
            print(f"Error: unknown format '{format_name}'. "
                  f"Available: {', '.join(sorted(importers))}",
                  file=sys.stderr)
            sys.exit(1)
        return importers[format_name]["module"].import_file(file_path)
    for name, info in importers.items():
        if info["module"].detect(file_path):
            return info["module"].import_file(file_path)
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
    if args.list_formats:
        _list_formats(_discover_exporters(), "export")
        return
    exporters = _discover_exporters()
    if args.format not in exporters:
        print(f"Error: unknown export format '{args.format}'. "
              f"Available: {', '.join(sorted(exporters))}",
              file=sys.stderr)
        sys.exit(1)
    if not args.output:
        print("Error: the following arguments are required: output", file=sys.stderr)
        sys.exit(1)

    from memex.db import Database
    exporter_mod = exporters[args.format]["module"]

    with Database(os.path.expanduser(args.db)) as db:
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
