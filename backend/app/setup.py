"""First-run setup for `python main.py`: pick the library folder, build the UI, serve."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .cache import write_atomic
from .config import CONFIG_PATH, PROJECT_ROOT, env_movies_dir, get_settings


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


def _read_choice() -> str:
    """Block until the user presses Enter or Esc; anything else is ignored."""
    if not sys.stdin.isatty():
        return "enter" if input().strip() == "" else "esc"
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
    raw = input("  movies folder (blank to use the default): ").strip().strip('"')
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


def prompt_for_movies_dir(initial: Path | None, default: str | None) -> str | None:
    """Run the Enter/Esc prompt.

    Returns the value to store in config.json, or None if the user declined and there
    is no MOVIES_DIR in .env to fall back to.
    """
    print()
    print("A folder picker window will open.")
    print("  [Enter]  open the picker and choose your movies folder")
    if default is None:
        print("  [Esc]    quit — .env sets no MOVIES_DIR, so a folder has to be picked")
    else:
        print(f"  [Esc]    cancel and use the default from .env ({_as_path(default)})")
    if not sys.stdin.isatty():
        print("  (not a terminal — press Enter for the picker, or type anything else to cancel)")

    if _read_choice() == "esc":
        if default is None:
            return None
        print(f"\ncancelled — using {_as_path(default)} from .env")
        return default

    print("\nopening the folder picker...")
    chosen = pick_directory(initial)
    if chosen is not None:
        return chosen.as_posix()
    if default is None:
        print("nothing selected.")
        return None
    print(f"nothing selected — using {_as_path(default)} from .env")
    return default


def resolve_movies_dir() -> Path | None:
    """Return the library folder, prompting for it once if the saved one is unusable.

    None means the user declined the picker and nothing else supplies a folder.
    """
    config = load_config()
    saved = _as_path(config.get("movies_dir"))

    if saved is not None and saved.is_dir():
        return saved

    if not CONFIG_PATH.exists():
        print(f"No {CONFIG_PATH.name} yet — let's set up your movie library.")
    elif saved is None:
        print(f"{CONFIG_PATH.name} has no usable 'movies_dir' — let's set it.")
    else:
        print(f"The movies folder saved in {CONFIG_PATH.name} is gone: {saved}")

    value = prompt_for_movies_dir(saved, env_movies_dir())
    if value is None:
        return None

    config["movies_dir"] = value
    save_config(config)
    print(f"saved to {CONFIG_PATH.name} — delete it to be asked again")

    chosen = _as_path(value)
    assert chosen is not None
    if not chosen.is_dir():
        # Prompting again would loop forever when the .env default is missing too.
        print(f"warning: {chosen} does not exist — the library will be empty until it does")
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
        chosen = resolve_movies_dir()
    except KeyboardInterrupt:
        print("\ncancelled.")
        return 1

    if chosen is None:
        print("\nNo movies folder chosen, so there is nothing to serve.")
        print("Run `python main.py` again, or set MOVIES_DIR in .env to have a default.")
        return 1

    get_settings.cache_clear()
    settings = get_settings()
    if settings.movies_dir != chosen:
        print(f"note: MOVIES_DIR in the environment overrides {CONFIG_PATH.name}")
    print(f"movies:  {settings.movies_dir}")
    print(f"cache:   {settings.cache_path}")

    ensure_frontend_build()

    print(f"\nserving http://{settings.host}:{settings.port}  (Ctrl-C to stop)\n")
    from .cli import main as cli_main

    return cli_main(["serve"])
