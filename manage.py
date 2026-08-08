#!/usr/bin/env python
"""Run movielister from the project root: `python manage.py sync --force`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from app.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
