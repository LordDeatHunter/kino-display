"""Disk-backed store for TMDB artwork.

The browser never talks to image.tmdb.org — it asks the backend, which fetches
each image once and keeps it under data/images/. That way a DNS hiccup or an
offline session cannot blank the poster grid.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

import httpx

from .cache import load_cache
from .config import MediaKind, Settings
from .models import DEFAULT_IMAGE_BASE

SIZES = frozenset({"w92", "w154", "w185", "w300", "w342", "w500", "w780", "w1280", "original"})
# TMDB artwork paths are a single content-addressed filename: /aBc123.jpg
PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|svg)$", re.IGNORECASE)

MAX_ATTEMPTS = 3
_locks: dict[str, asyncio.Lock] = {}


class ImageError(RuntimeError):
    """The image could not be fetched — network, timeout or upstream error."""


class ImageNotFound(ImageError):
    """TMDB has no such artwork; retrying will not help."""


def normalize_path(path: str) -> str:
    """Accept "abc.jpg" or "/abc.jpg"; reject anything else."""
    candidate = path if path.startswith("/") else f"/{path}"
    if not PATH_RE.match(candidate):
        raise ValueError(f"Unsupported image path: {path!r}")
    return candidate


def local_path(settings: Settings, size: str, path: str) -> Path:
    """Where a given image lives on disk. Validates both parts — they are used
    to build a filesystem path, so this is the traversal guard."""
    if size not in SIZES:
        raise ValueError(f"Unsupported image size: {size!r}")
    return settings.images_dir / size / normalize_path(path).lstrip("/")


def upstream_base(settings: Settings, kind: MediaKind = "movies") -> str:
    return load_cache(settings.cache_path_for(kind)).image_base_url or DEFAULT_IMAGE_BASE


async def _download(client: httpx.AsyncClient, url: str, destination: Path) -> None:
    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code == 404:
                raise ImageNotFound(f"404 from TMDB for {url}")
            if response.status_code < 400:
                _write_atomic(destination, response.content)
                return
            last_error = f"HTTP {response.status_code}"
        await asyncio.sleep(2**attempt)
    raise ImageError(f"Could not fetch {url}: {last_error}")


def _write_atomic(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "wb", dir=destination.parent, prefix=destination.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, destination)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


async def fetch_image(
    settings: Settings,
    size: str,
    path: str,
    *,
    client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
) -> tuple[Path, bool]:
    """Return the on-disk image and whether it was already cached."""
    destination = local_path(settings, size, path)
    if destination.exists():
        return destination, True

    key = f"{size}{normalize_path(path)}"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # Another request may have downloaded it while we waited.
        if destination.exists():
            return destination, True

        url = f"{base_url or upstream_base(settings)}{size}{normalize_path(path)}"
        if client is not None:
            await _download(client, url, destination)
        else:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as owned:
                await _download(owned, url, destination)

    return destination, False


def wanted_images(
    settings: Settings,
    *,
    backdrops: bool,
    cast: bool,
    stills: bool = False,
    kind: MediaKind = "movies",
) -> list[tuple[str, str]]:
    """Every (size, path) pair the UI could ask for, de-duplicated."""
    cache = load_cache(settings.cache_path_for(kind))
    seen: set[str] = set()
    wanted: list[tuple[str, str]] = []
    for entry in cache.entries.values():
        if entry.tmdb is None:
            continue
        candidates: list[tuple[str, str | None]] = [("w342", entry.tmdb.poster_path)]
        # Season posters are on screen as soon as a show's modal opens, so they
        # belong in the base set; episode stills are one click deeper.
        candidates += [("w185", season.poster_path) for season in entry.tmdb.seasons]
        if backdrops:
            candidates.append(("w1280", entry.tmdb.backdrop_path))
        if cast:
            candidates += [("w185", member.profile_path) for member in entry.tmdb.cast]
        if stills:
            candidates += [
                ("w300", episode.still_path)
                for season in entry.tmdb.seasons
                for episode in season.episodes
            ]
        for size, path in candidates:
            if not path:
                continue
            key = f"{size}{path}"
            if key not in seen:
                seen.add(key)
                wanted.append((size, path))
    return wanted


async def prefetch(
    settings: Settings,
    *,
    backdrops: bool = False,
    cast: bool = False,
    stills: bool = False,
    kind: MediaKind = "movies",
    progress: object = None,
) -> tuple[int, int, list[str]]:
    """Warm the store from the kind's cache. Returns (downloaded, skipped, errors)."""
    targets = wanted_images(settings, backdrops=backdrops, cast=cast, stills=stills, kind=kind)
    base = upstream_base(settings, kind)
    semaphore = asyncio.Semaphore(max(1, settings.max_concurrency))
    downloaded = skipped = 0
    errors: list[str] = []

    if not targets:
        return 0, 0, []

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True) as client:

        async def one(size: str, path: str) -> tuple[str, bool | None, str]:
            async with semaphore:
                try:
                    _, hit = await fetch_image(settings, size, path, client=client, base_url=base)
                    return f"{size}{path}", hit, ""
                except (ImageError, ValueError) as exc:
                    return f"{size}{path}", None, str(exc)

        tasks = [asyncio.create_task(one(size, path)) for size, path in targets]
        done = 0
        for coro in asyncio.as_completed(tasks):
            label, hit, error = await coro
            if error:
                errors.append(error)
            elif hit:
                skipped += 1
            else:
                downloaded += 1
            done += 1
            if callable(progress):
                progress(done, len(targets), label)

    return downloaded, skipped, errors


def cached_files(settings: Settings) -> tuple[int, int]:
    """(file count, total bytes) currently held in the image store."""
    if not settings.images_dir.is_dir():
        return 0, 0
    files = [p for p in settings.images_dir.rglob("*") if p.is_file() and not p.name.endswith(".tmp")]
    return len(files), sum(p.stat().st_size for p in files)
