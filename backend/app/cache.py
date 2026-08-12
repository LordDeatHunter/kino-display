"""Atomic JSON persistence for the metadata cache and the manual overrides."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import SCHEMA_VERSION, CacheFile


def write_atomic(path: Path, payload: str) -> None:
    """Write text so a crash mid-write can never leave a half-file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def load_cache(path: Path) -> CacheFile:
    """Read the cache, returning an empty one if it is missing or unreadable."""
    if not path.exists():
        return CacheFile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cache = CacheFile.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        return CacheFile()
    if cache.schema_version != SCHEMA_VERSION:
        return CacheFile()
    return cache


def save_cache(path: Path, cache: CacheFile) -> None:
    write_atomic(path, cache.model_dump_json(indent=2, exclude_none=False))


def load_overrides(path: Path) -> dict[str, int | None]:
    """Read `{"folder name": tmdb_id}`; a null value means "ignore this folder"."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, int | None] = {}
    for key, value in data.items():
        if value is None:
            result[str(key)] = None
        elif isinstance(value, (int, str)) and str(value).isdigit():
            result[str(key)] = int(value)
    return result


def save_overrides(path: Path, overrides: dict[str, int | None]) -> None:
    ordered = {key: overrides[key] for key in sorted(overrides, key=str.lower)}
    write_atomic(path, json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
