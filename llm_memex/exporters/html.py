"""Export conversations as a self-contained HTML SPA directory."""
import os
import shutil
import sqlite3
from pathlib import Path
from typing import List

from llm_memex.db import Database
from llm_memex.exporters.html_template import get_template
from llm_memex.models import Conversation


_VENDORED_DIR = Path(__file__).parent / "vendored"
_SQL_JS_FILES = ("sql-wasm.js", "sql-wasm.wasm")
_FTS5_TABLES = ("messages_fts", "notes_fts")


def _strip_fts5_and_vacuum(db_path: Path) -> None:
    """Drop FTS5 virtual tables and VACUUM.

    sql.js (used by the HTML SPA) cannot query FTS5 — it's not compiled in.
    The shadow tables are ~50% of a typical DB, so dropping them before
    export roughly halves bundle size. The SPA falls back to LIKE queries.

    Sets ``PRAGMA journal_mode=DELETE`` on the copy so no -wal/-shm sidecar
    files are left next to the exported database when the process is
    interrupted, and a subsequent VACUUM produces a fully-packed file.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        for fts in _FTS5_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {fts}")
        conn.commit()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("VACUUM")


def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    """Export as HTML SPA directory: index.html + sql-wasm.{js,wasm} + conversations.db + assets/.

    Creates a directory at *path* containing:
    - index.html  -- the single-page application
    - sql-wasm.js, sql-wasm.wasm  -- vendored sql.js (no CDN dependency)
    - conversations.db  -- copy of the source database with FTS5 stripped
      (if db_path provided)
    - assets/  -- copy of media assets directory (if it exists next to db_path)

    Parameters
    ----------
    conversations : list[Conversation]
        Not used directly (the DB copy carries all data), but accepted for
        exporter API compatibility.
    path : str
        Destination directory to create/populate.
    **kwargs :
        db_path : str, optional
            Path to the source conversations.db file.  When provided (and not
            ``":memory:"``), the DB and its sibling ``assets/`` directory are
            copied into the output.
    """
    out_dir = Path(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    db_path = kwargs.get("db_path")
    has_db = db_path and db_path != ":memory:" and os.path.exists(db_path)

    # Extract schema DDL from the database if available
    schema_ddl = ""
    if has_db:
        try:
            with Database(str(Path(db_path).parent), readonly=True) as db:
                schema_ddl = db.get_schema()
        except Exception:
            pass

    # Write index.html
    (out_dir / "index.html").write_text(get_template(schema_ddl=schema_ddl))

    # Vendor sql.js (no CDN dependency)
    for filename in _SQL_JS_FILES:
        src = _VENDORED_DIR / filename
        if src.exists():
            shutil.copy2(src, out_dir / filename)

    # Copy DB (stripping FTS5 shadow tables) and assets
    if has_db:
        dest_db = out_dir / "conversations.db"
        shutil.copy2(db_path, dest_db)
        _strip_fts5_and_vacuum(dest_db)
        assets_dir = Path(db_path).parent / "assets"
        if assets_dir.is_dir():
            dest_assets = out_dir / "assets"
            if dest_assets.exists():
                shutil.rmtree(dest_assets)
            shutil.copytree(assets_dir, dest_assets)
