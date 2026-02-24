"""Scripts framework — discovery and runner utilities.

Convention: each script is a Python module with:
    register_args(parser)  — add script-specific CLI arguments
    run(db, args, apply)   — execute the script, return stats dict
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional


def _builtin_dir() -> Path:
    return Path(__file__).parent


def _user_dir() -> Path:
    return Path.home() / ".memex" / "scripts"


def _load_module(name: str, path: Path):
    """Load a Python module from a file path."""
    spec = importlib.util.spec_from_file_location(f"memex_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_description(mod) -> str:
    """Extract first line of module docstring as description."""
    doc = getattr(mod, "__doc__", None) or ""
    first_line = doc.strip().split("\n")[0].strip()
    return first_line


def discover_scripts() -> Dict[str, Dict[str, Any]]:
    """Discover available scripts from built-in and user directories.

    Returns dict mapping script name to {"path": Path, "description": str}.
    User scripts shadow built-in scripts of the same name.
    """
    scripts: Dict[str, Dict[str, Any]] = {}

    for d in [_builtin_dir(), _user_dir()]:
        if not d.exists():
            continue
        for py_file in sorted(d.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            name = py_file.stem
            try:
                mod = _load_module(name, py_file)
            except Exception:
                continue
            if not (hasattr(mod, "register_args") and hasattr(mod, "run")):
                continue
            scripts[name] = {
                "path": py_file,
                "description": _extract_description(mod),
            }

    return scripts


def load_script(name: str):
    """Load a script module by name.

    Raises ValueError if script is not found.
    """
    scripts = discover_scripts()
    if name not in scripts:
        raise ValueError(f"Script '{name}' not found. Use 'memex run --list' to see available scripts.")
    return _load_module(name, scripts[name]["path"])
