"""Show a library folder in the file manager of the machine running the server.

The browser cannot do this itself: a file:// link from an http:// page is blocked
outright, and nothing in the web platform launches a file manager. Since movielister
serves localhost, doing it server-side lands on the same desktop the click came from.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class RevealError(RuntimeError):
    """The file manager could not be launched."""


def _run(command: list[str]) -> None:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RevealError(f"{command[0]} exited with {result.returncode}")


def reveal(path: Path) -> None:
    """Show `path` in the desktop file manager, selecting it if it is a file."""
    try:
        if sys.platform == "win32":
            _reveal_windows(path)
        elif sys.platform == "darwin":
            _run(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
        else:
            # No reveal on xdg-open, so a loose video file opens its folder instead.
            _run(["xdg-open", str(path if path.is_dir() else path.parent)])
    except OSError as exc:
        raise RevealError(f"could not open {path}: {exc}") from exc


def _reveal_windows(path: Path) -> None:
    if not path.is_file():
        os.startfile(path)  # noqa: S606 — the path came from our own library scan
        return

    # One string, not a list: list2cmdline would wrap "/select," and the path in a
    # single pair of quotes, which Explorer reads as one malformed switch. Windows
    # forbids '"' in filenames, so quoting the path by hand is safe. The return code
    # is ignored because Explorer answers 1 even when it worked.
    subprocess.run(f'explorer /select,"{path}"', check=False)
