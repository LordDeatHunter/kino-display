"""First-run setup for `python main.py`: pick the library folders, build the UI, serve."""

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
    PROJECT_ROOT,
    env_movies_dirs,
    get_settings,
)


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


def config_movies_dirs(config: dict) -> list[Path]:
    """Folders saved in config.json, falling back to the legacy singular key."""
    raw = config.get("movies_dirs", config.get("movies_dir"))
    return _as_paths(raw)


def save_movies_dirs(config: dict, values: list[str]) -> None:
    config.pop("movies_dir", None)  # superseded by the list
    config["movies_dirs"] = values
    save_config(config)


def _read_choice() -> str:
    """Block until the user presses Enter or Esc; anything else is ignored."""
    if not sys.stdin.isatty():
        try:
            return "enter" if input().strip() == "" else "esc"
        except EOFError:
            return "esc"
    while True:
        key = _read_key()
        if key in ("\r", "\n"):
            return "enter"
        if key == "\x1b":
            return "esc"
        if key == "\x03":
            raise KeyboardInterrupt


def _read_key() -> str:
    if os.name == "nt":
        import msvcrt

        char = msvcrt.getch()
        if char in (b"\x00", b"\xe0"):  # arrow / function key: drop the second byte
            msvcrt.getch()
            return ""
        return char.decode("latin-1")

    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _typed_directory() -> Path | None:
    raw = input("  movies folder to add (blank to cancel): ").strip().strip('"')
    return Path(raw) if raw else None


def pick_directory(initial: Path | None) -> Path | None:
    """Open the OS folder picker. Returns None if it is cancelled or unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("  tkinter is not installed, so the picker cannot open — type a path instead.")
        return _typed_directory()

    options: dict[str, object] = {"title": "Select your movies folder", "mustexist": True}
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
        return _typed_directory()
    return Path(chosen) if chosen else None


def _describe(paths: list[Path]) -> None:
    for index, path in enumerate(paths, 1):
        note = "" if path.is_dir() else "   (missing)"
        print(f"  {index}. {path}{note}")


def current_movies_dirs(config: dict) -> tuple[list[Path], str]:
    """The folders in force right now, plus a label for where they came from."""
    saved = config_movies_dirs(config)
    if saved:
        return saved, CONFIG_PATH.name
    from_env = _as_paths(env_movies_dirs() or [])
    if from_env:
        return from_env, "MOVIES_DIRS"
    # The built-in default is only worth offering if it happens to be there; seeding a
    # brand-new config.json with a folder that does not exist helps nobody.
    fallback = [path for path in _as_paths([DEFAULT_MOVIES_DIR]) if path.is_dir()]
    return fallback, "the default"


def prompt_for_movies_dirs(current: list[Path], source: str) -> list[Path]:
    """Show the folders in use and add more, one per round, until the user is done.

    Returns the folders to use — the ones passed in, unchanged, if the user just
    presses Esc.
    """
    chosen = list(current)
    while True:
        print()
        if chosen:
            # The source only describes the folders as they were found, not additions.
            print(f"movies folders (from {source}):" if chosen == current else "movies folders:")
            _describe(chosen)
            print("  [Enter]  open the picker and add another folder")
            print("  [Esc]    continue with these")
        else:
            print("No movies folders are set.")
            print("  [Enter]  open the picker and choose your movies folder")
            print("  [Esc]    continue anyway — there will be nothing to scan")
        if not sys.stdin.isatty():
            print("  (not a terminal — press Enter for the picker, or anything else to continue)")

        if _read_choice() == "esc":
            return chosen

        print("\nopening the folder picker...")
        picked = pick_directory(chosen[-1] if chosen else None)
        resolved = None if picked is None else _as_path(picked.as_posix())
        if resolved is None:
            print("nothing selected.")
        elif resolved in chosen:
            print("already added.")
        else:
            chosen.append(resolved)


def resolve_movies_dirs() -> list[Path]:
    """Show the library folders on every run, letting the user append to them.

    Anything added is written to config.json — created on the spot if this is the
    first run, appended to otherwise. Esc leaves the config exactly as it was.
    """
    config = load_config()
    if "movies_dirs" not in config and config_movies_dirs(config):
        # Upgrade the pre-list key in place so the saved value matches what is shown.
        save_movies_dirs(config, [path.as_posix() for path in config_movies_dirs(config)])
        print(f"note: 'movies_dir' in {CONFIG_PATH.name} is now the list 'movies_dirs'")

    current, source = current_movies_dirs(config)
    chosen = prompt_for_movies_dirs(current, source)

    if chosen != current:
        save_movies_dirs(config, [path.as_posix() for path in chosen])
        print(f"\nsaved to {CONFIG_PATH.name}")
    return chosen


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


def main() -> int:
    try:
        chosen = resolve_movies_dirs()
    except KeyboardInterrupt:
        print("\ncancelled.")
        return 1

    get_settings.cache_clear()
    settings = get_settings()
    if settings.movies_dirs != chosen:
        print(f"note: MOVIES_DIRS in the environment overrides {CONFIG_PATH.name}")
    for index, path in enumerate(settings.movies_dirs):
        note = "" if path.is_dir() else "   (missing — nothing will be scanned from it)"
        print(f"{'movies:' if index == 0 else '':<9}{path}{note}")
    if not settings.movies_dirs:
        print("movies:  none set — add one with `python main.py` or in config.json")
    print(f"cache:   {settings.cache_path}")

    ensure_frontend_build()

    print(f"\nserving http://{settings.host}:{settings.port}  (Ctrl-C to stop)\n")
    from .cli import main as cli_main

    return cli_main(["serve"])
