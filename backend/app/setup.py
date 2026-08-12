"""Startup for `python main.py`: the launcher menu, the frontend build, then serve."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .cache import write_atomic
from .config import (
    CONFIG_PATH,
    DEFAULT_MOVIES_DIR,
    MEDIA_KINDS,
    PROJECT_ROOT,
    MediaKind,
    env_library_dirs,
    get_settings,
)

# config.json key per library.
CONFIG_KEYS: dict[MediaKind, str] = {"movies": "movies_dirs", "series": "series_dirs"}


def load_config() -> dict:
    """Read config.json, returning an empty dict if it is missing or unreadable."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict) -> None:
    write_atomic(CONFIG_PATH, json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def _as_path(raw: object) -> Path | None:
    """Mirror Settings._resolve: relative paths resolve against the project root."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw.strip())
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _as_paths(raw: object) -> list[Path]:
    """Mirror Settings: a list of paths, or one os.pathsep-separated string."""
    items = raw if isinstance(raw, list) else [raw]
    paths: list[Path] = []
    for item in items:
        if not isinstance(item, str):
            continue
        for part in item.split(os.pathsep):
            path = _as_path(part)
            if path is not None and path not in paths:
                paths.append(path)
    return paths


def config_dirs(config: dict, kind: MediaKind) -> list[Path]:
    """Folders saved in config.json, falling back to the legacy singular key."""
    key = CONFIG_KEYS[kind]
    raw = config.get(key, config.get(key.removesuffix("s")))
    return _as_paths(raw)


def save_dirs(config: dict, kind: MediaKind, values: list[str]) -> None:
    key = CONFIG_KEYS[kind]
    config.pop(key.removesuffix("s"), None)  # superseded by the list
    config[key] = values
    save_config(config)


def _typed_directory(kind: MediaKind) -> Path | None:
    raw = input(f"  {kind} folder to add (blank to cancel): ").strip().strip('"')
    return Path(raw) if raw else None


def pick_directory(initial: Path | None, kind: MediaKind = "movies") -> Path | None:
    """Open the OS folder picker. Returns None if it is cancelled or unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("  tkinter is not installed, so the picker cannot open — type a path instead.")
        return _typed_directory(kind)

    options: dict[str, object] = {"title": f"Select a {kind} folder", "mustexist": True}
    if initial is not None and initial.is_dir():
        options["initialdir"] = str(initial)
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(**options)
        finally:
            root.destroy()
    except tk.TclError as exc:
        print(f"  the picker could not open ({exc}) — type a path instead.")
        return _typed_directory(kind)
    return Path(chosen) if chosen else None


def resolve_path(raw: str) -> Path | None:
    """Turn a picked or typed path into the absolute form config.json stores."""
    return _as_path(raw)


def current_dirs(config: dict, kind: MediaKind) -> tuple[list[Path], str]:
    """The folders in force right now, plus a label for where they came from."""
    saved = config_dirs(config, kind)
    if saved:
        return saved, CONFIG_PATH.name
    from_env = _as_paths(env_library_dirs(kind) or [])
    if from_env:
        return from_env, f"{kind.upper()}_DIRS"
    if kind == "series":
        return [], "nothing yet"
    # The built-in default is only worth offering if it happens to be there; seeding a
    # brand-new config.json with a folder that does not exist helps nobody.
    fallback = [path for path in _as_paths([DEFAULT_MOVIES_DIR]) if path.is_dir()]
    return fallback, "the default"


def upgrade_legacy_keys() -> dict:
    """Rewrite any pre-list "movies_dir" key so what is saved matches what is shown."""
    config = load_config()
    for kind in MEDIA_KINDS:
        key = CONFIG_KEYS[kind]
        if key not in config and config_dirs(config, kind):
            save_dirs(config, kind, [path.as_posix() for path in config_dirs(config, kind)])
            print(f"note: '{key.removesuffix('s')}' in {CONFIG_PATH.name} is now the list '{key}'")
    return config


def _run(command: list[str], cwd: Path) -> bool:
    print(f"  $ npm {' '.join(command[1:])}")
    try:
        return subprocess.run(command, cwd=cwd, check=False).returncode == 0
    except OSError as exc:
        print(f"  failed to run {command[0]}: {exc}")
        return False


def ensure_frontend_build() -> None:
    """Build frontend/dist if it is missing — FastAPI mounts it at import time."""
    dist = get_settings().frontend_dist
    if (dist / "index.html").is_file():
        return

    frontend = PROJECT_ROOT / "frontend"
    npm = shutil.which("npm")
    if npm is None:
        print(f"\n{dist} is missing and npm was not found on PATH.")
        print("  the API will still run, but the web UI will not load.")
        return

    print("\nbuilding the web UI (first run only, this takes a minute)")
    if not (frontend / "node_modules").is_dir() and not _run([npm, "install"], frontend):
        print("  npm install failed — the API will run, but the web UI will not load.")
        return
    if not _run([npm, "run", "build"], frontend):
        print("  npm run build failed — the API will run, but the web UI will not load.")


def _describe_libraries(config: dict) -> None:
    """Print the folders each library will actually scan, and where they came from."""
    settings = get_settings()
    for kind in MEDIA_KINDS:
        in_use = settings.library_dirs(kind)
        saved = config_dirs(config, kind)
        if saved and in_use != saved:
            print(f"note: {kind.upper()}_DIRS in the environment overrides {CONFIG_PATH.name}")
        if not in_use:
            print(f"{kind + ':':<9}none set — add one with `python main.py`")
            continue
        for index, path in enumerate(in_use):
            note = "" if path.is_dir() else "   (missing — nothing will be scanned from it)"
            print(f"{kind + ':' if index == 0 else '':<9}{path}{note}")
        print(f"{'':<9}cache: {settings.cache_path_for(kind)}")


def main() -> int:
    try:
        config = upgrade_legacy_keys()
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_launcher

            if not run_launcher():
                print("closed without starting.")
                return 0
        # Without a terminal there is no menu to show — a piped or scheduled run
        # goes straight to serving whatever config.json already says.
    except KeyboardInterrupt:
        print("\ncancelled.")
        return 1

    # The launcher may have rewritten config.json since settings were last read.
    get_settings.cache_clear()
    _describe_libraries(load_config() or config)

    ensure_frontend_build()

    settings = get_settings()
    print(f"\nserving http://{settings.host}:{settings.port}  (Ctrl-C to stop)\n")
    from .cli import main as cli_main

    return cli_main(["serve"])
