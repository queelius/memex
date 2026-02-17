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

    # serve
    sub.add_parser("serve", help="Start MCP server")

    args = parser.parse_args()
    if args.command == "import":
        _cmd_import(args)
    elif args.command == "export":
        _cmd_export(args)
    elif args.command == "serve":
        _cmd_serve(args)
    else:
        parser.print_help()


def _get_version():
    from memex import __version__

    return __version__


def _cmd_import(args):
    from memex.db import Database

    db_path = os.path.expanduser(args.db)
    db = Database(db_path)
    convs = _auto_import(args.file, args.format)
    for conv in convs:
        db.save_conversation(conv)
    print(f"Imported {len(convs)} conversation(s) into {db_path}")
    db.close()


def _auto_import(file_path, format_name=None):
    """Auto-detect importer and import file."""
    importers_dir = Path(__file__).parent / "importers"
    user_dir = Path.home() / ".memex" / "importers"
    for d in [user_dir, importers_dir]:
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
    print(f"No importer found for {file_path}", file=sys.stderr)
    return []


def _cmd_export(args):
    from memex.db import Database

    db = Database(os.path.expanduser(args.db))
    result = db.query_conversations(limit=10000)
    convs = [db.load_conversation(item["id"]) for item in result["items"]]
    convs = [c for c in convs if c is not None]
    exporters_dir = Path(__file__).parent / "exporters"
    for py_file in exporters_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        if py_file.stem == args.format or py_file.stem == f"{args.format}_export":
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "export"):
                mod.export(convs, args.output)
                print(f"Exported {len(convs)} conversation(s) to {args.output}")
                db.close()
                return
    print(f"Unknown export format: {args.format}", file=sys.stderr)
    db.close()


def _cmd_serve(args):
    from memex.server import main as serve_main

    serve_main()


if __name__ == "__main__":
    main()
