#!/usr/bin/env python
"""Start movielister: `python main.py`. Asks for your library folder on first run."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.setup import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
