"""Export conversations as a self-contained HTML SPA directory."""
import os
import shutil
from pathlib import Path
from typing import List

from memex.exporters.html_template import get_template
from memex.models import Conversation


def export(conversations: List[Conversation], path: str, **kwargs) -> None:
    """Export as HTML SPA directory: index.html + conversations.db + assets/.

    Creates a directory at *path* containing:
    - index.html  -- the single-page application (loads sql.js via CDN)
    - conversations.db  -- copy of the source database (if db_path provided)
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

    # Write index.html
    (out_dir / "index.html").write_text(get_template())

    # Copy DB if available
    db_path = kwargs.get("db_path")
    if db_path and db_path != ":memory:" and os.path.exists(db_path):
        shutil.copy2(db_path, out_dir / "conversations.db")

        # Copy assets if they exist
        assets_dir = Path(db_path).parent / "assets"
        if assets_dir.is_dir():
            dest_assets = out_dir / "assets"
            if dest_assets.exists():
                shutil.rmtree(dest_assets)
            shutil.copytree(assets_dir, dest_assets)
