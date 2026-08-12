"""Diff the library against the cache and fetch only what is missing."""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable, Iterable
from pathlib import Path

from .cache import load_cache, load_overrides, save_cache
from .config import Settings
from .models import CacheEntry, CacheFile, ScannedEntry, SyncReport
from .scanner import scan_libraries
from .tmdb import TmdbClient, TmdbError

CHECKPOINT_EVERY = 25
LOW_CONFIDENCE_THRESHOLD = 0.75

ProgressCallback = Callable[[int, int, str], None]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _under_any(path: str, roots: list[Path]) -> bool:
    candidate = Path(path)
    return any(candidate.is_relative_to(root) for root in roots)


def _needs_fetch(
    entry: CacheEntry | None,
    override: int | None,
    has_override: bool,
    *,
    force: bool,
    retry_unmatched: bool,
) -> bool:
    if entry is None or force:
        return True
    if has_override:
        # A new or changed override must win over whatever the search found.
        if override is None:
            return entry.status != "ignored"
        return entry.source != "override" or (entry.tmdb.id if entry.tmdb else None) != override
    if entry.source == "override" or entry.status == "ignored":
        # The override was removed — fall back to a normal search.
        return True
    if retry_unmatched and entry.status != "matched":
        return True
    return entry.status == "error"


async def _resolve(
    client: TmdbClient,
    scanned: ScannedEntry,
    override: int | None,
    has_override: bool,
) -> CacheEntry:
    entry = CacheEntry(
        dir_name=scanned.dir_name,
        path=scanned.path,
        is_file=scanned.is_file,
        parsed_title=scanned.parsed_title,
        parsed_year=scanned.parsed_year,
        fetched_at=_now(),
    )

    if has_override and override is None:
        entry.status = "ignored"
        entry.source = "override"
        return entry

    try:
        if has_override and override is not None:
            entry.tmdb = await client.details(override)
            entry.status = "matched"
            entry.source = "override"
            entry.match_confidence = 1.0
            return entry

        best, score = await client.find_best(scanned.parsed_title, scanned.parsed_year)
        if best is None:
            entry.status = "unmatched"
            return entry

        entry.tmdb = await client.details(int(best["id"]))
        entry.status = "matched"
        entry.source = "search"
        entry.match_confidence = round(score, 3)
        entry.low_confidence = score < LOW_CONFIDENCE_THRESHOLD or scanned.parsed_year is None
    except TmdbError as exc:
        entry.status = "error"
        entry.error = str(exc)
    return entry

async def run_sync(
    settings: Settings,
    *,
    force: bool = False,
    retry_unmatched: bool = False,
    only: Iterable[str] | None = None,
    progress: ProgressCallback | None = None,
) -> SyncReport:
    """Bring the cache in line with the library, fetching as little as possible."""
    scanned, _notes = scan_libraries(settings.movies_dirs)
    by_name = {item.dir_name: item for item in scanned}
    offline = [path for path in settings.movies_dirs if not path.exists()]
    cache = load_cache(settings.cache_path)
    overrides = load_overrides(settings.overrides_path)
    only_set = set(only) if only is not None else None
    # Naming folders explicitly is a request to refetch them, whatever the cache says.
    force = force or only_set is not None

    report = SyncReport()

    # Folders that vanished from disk drop out of the cache — unless the library folder
    # they live in is the thing that vanished, which is an unplugged drive, not 300
    # deletions.
    for dir_name, entry in list(cache.entries.items()):
        if dir_name in by_name or _under_any(entry.path, offline):
            continue
        del cache.entries[dir_name]
        report.removed.append(dir_name)

    todo: list[ScannedEntry] = []
    for item in scanned:
        if only_set is not None and item.dir_name not in only_set:
            continue
        existing = cache.entries.get(item.dir_name)
        has_override = item.dir_name in overrides
        if _needs_fetch(
            existing,
            overrides.get(item.dir_name),
            has_override,
            force=force,
            retry_unmatched=retry_unmatched,
        ):
            todo.append(item)
            (report.added if existing is None else report.refetched).append(item.dir_name)
        else:
            report.unchanged += 1
            # Folders can be moved without being renamed.
            if existing is not None and existing.path != item.path:
                existing.path = item.path

    total = len(todo)
    if progress:
        progress(0, total, "")

    if total:
        async with TmdbClient(settings) as client:
            cache.image_base_url = await client.image_base_url()
            tasks = [
                asyncio.create_task(
                    _resolve(client, item, overrides.get(item.dir_name), item.dir_name in overrides)
                )
                for item in todo
            ]
            done = 0
            for coro in asyncio.as_completed(tasks):
                entry = await coro
                cache.entries[entry.dir_name] = entry
                if entry.status == "error":
                    report.errors.append(f"{entry.dir_name}: {entry.error}")
                done += 1
                if progress:
                    progress(done, total, entry.dir_name)
                if done % CHECKPOINT_EVERY == 0:
                    cache.synced_at = _now()
                    save_cache(settings.cache_path, cache)

    report.unmatched = sum(1 for entry in cache.entries.values() if entry.status == "unmatched")
    cache.synced_at = _now()
    save_cache(settings.cache_path, cache)
    return report


async def resolve_single(settings: Settings, dir_name: str) -> CacheEntry | None:
    """Refetch one folder (used after an override is set from the UI)."""
    entries, _notes = scan_libraries(settings.movies_dirs)
    item = {entry.dir_name: entry for entry in entries}.get(dir_name)
    if item is None:
        return None

    overrides = load_overrides(settings.overrides_path)
    cache = load_cache(settings.cache_path)
    async with TmdbClient(settings) as client:
        cache.image_base_url = await client.image_base_url()
        entry = await _resolve(client, item, overrides.get(dir_name), dir_name in overrides)

    cache.entries[dir_name] = entry
    cache.synced_at = _now()
    save_cache(settings.cache_path, cache)
    return entry


def read_cache(settings: Settings) -> CacheFile:
    return load_cache(settings.cache_path)
