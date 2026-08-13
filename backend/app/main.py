"""FastAPI application: serves the cached library and drives syncs."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cache import load_cache, load_overrides, save_cache, save_overrides
from .config import MEDIA_KINDS, MediaKind, get_settings
from .images import ImageError, ImageNotFound, fetch_image
from .models import (
    CacheEntry,
    CacheFile,
    ConfirmRequest,
    OpenRequest,
    OverrideRequest,
    SyncStatus,
)
from .reveal import RevealError, reveal
from .sync import read_cache, resolve_single, run_sync, under_any
from .tmdb import TmdbClient, TmdbError

app = FastAPI(title="Movielister", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Each library syncs on its own, so a long series sync never blocks a movie one.
_status: dict[MediaKind, SyncStatus] = {kind: SyncStatus(kind=kind) for kind in MEDIA_KINDS}
_sync_locks: dict[MediaKind, asyncio.Lock] = {kind: asyncio.Lock() for kind in MEDIA_KINDS}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@app.get("/api/library", response_model=CacheFile)
def get_library(kind: MediaKind = Query("movies")) -> CacheFile:
    return read_cache(get_settings(), kind)


@app.get("/api/stats")
def get_stats(kind: MediaKind = Query("movies")) -> dict[str, object]:
    settings = get_settings()
    cache = read_cache(settings, kind)
    entries = list(cache.entries.values())
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return {
        "kind": kind,
        "total": len(entries),
        "by_status": counts,
        "low_confidence": sum(1 for e in entries if e.low_confidence and e.status == "matched"),
        "synced_at": cache.synced_at,
        "dirs": [str(path) for path in settings.library_dirs(kind)],
    }


async def _run_sync_job(kind: MediaKind, force: bool, retry_unmatched: bool) -> None:
    status = _status[kind]

    def progress(done: int, total: int, current: str) -> None:
        status.done = done
        status.total = total
        status.current = current

    try:
        status.report = await run_sync(
            get_settings(), kind=kind, force=force, retry_unmatched=retry_unmatched, progress=progress
        )
        status.error = None
    except Exception as exc:  # surfaced to the UI rather than lost in the server log
        status.error = f"{type(exc).__name__}: {exc}"
    finally:
        status.running = False
        status.finished_at = _now()
        _sync_locks[kind].release()


@app.post("/api/sync", response_model=SyncStatus)
async def start_sync(
    kind: MediaKind = Query("movies"),
    force: bool = Query(False),
    retry_unmatched: bool = Query(False),
) -> SyncStatus:
    lock = _sync_locks[kind]
    if lock.locked():
        raise HTTPException(status_code=409, detail=f"A {kind} sync is already running")
    await lock.acquire()

    status = _status[kind]
    status.running = True
    status.done = 0
    status.total = 0
    status.current = ""
    status.started_at = _now()
    status.finished_at = ""
    status.report = None
    status.error = None

    asyncio.create_task(_run_sync_job(kind, force, retry_unmatched))
    return status


@app.get("/api/sync/status", response_model=SyncStatus)
def sync_status(kind: MediaKind = Query("movies")) -> SyncStatus:
    return _status[kind]


@app.get("/api/img/{size}/{filename}")
async def get_image(size: str, filename: str) -> FileResponse:
    """Serve TMDB artwork from disk, fetching it once on the first request."""
    settings = get_settings()
    try:
        path, hit = await fetch_image(settings, size, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImageNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return FileResponse(
        path,
        headers={
            # TMDB paths are content-addressed, so a cached image never goes stale.
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Cache": "HIT" if hit else "MISS",
        },
    )


@app.get("/api/tmdb/search")
async def tmdb_search(
    q: str = Query(min_length=1),
    year: int | None = None,
    kind: MediaKind = Query("movies"),
) -> dict[str, object]:
    settings = get_settings()
    try:
        async with TmdbClient(settings, kind) as client:
            results = await client.search(q, year)
            image_base = await client.image_base_url()
    except (TmdbError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "image_base_url": image_base,
        "results": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "original_title": item.get("original_title"),
                "release_date": item.get("release_date"),
                "overview": item.get("overview"),
                "poster_path": item.get("poster_path"),
                "vote_average": item.get("vote_average"),
            }
            for item in results[:12]
        ],
    }


@app.post("/api/overrides", response_model=CacheEntry)
async def set_override(request: OverrideRequest) -> CacheEntry:
    settings = get_settings()
    path = settings.overrides_path_for(request.kind)
    overrides = load_overrides(path)
    overrides[request.dir_name] = request.tmdb_id
    save_overrides(path, overrides)

    entry = await resolve_single(settings, request.dir_name, request.kind)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such folder: {request.dir_name}")
    return entry


@app.delete("/api/overrides/{dir_name:path}", response_model=CacheEntry)
async def clear_override(dir_name: str, kind: MediaKind = Query("movies")) -> CacheEntry:
    settings = get_settings()
    path = settings.overrides_path_for(kind)
    overrides = load_overrides(path)
    overrides.pop(dir_name, None)
    save_overrides(path, overrides)

    entry = await resolve_single(settings, dir_name, kind)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such folder: {dir_name}")
    return entry


@app.get("/api/overrides")
def get_overrides(kind: MediaKind = Query("movies")) -> dict[str, int | None]:
    return load_overrides(get_settings().overrides_path_for(kind))


@app.post("/api/confirm", response_model=list[CacheEntry])
def confirm_matches(request: ConfirmRequest) -> list[CacheEntry]:
    """Accept the match a folder already has.

    Pins it as an override so it survives `--force` and never drifts back to a
    search result, and clears the low-confidence flag. No network needed — the
    metadata is already cached.
    """
    settings = get_settings()
    cache_path = settings.cache_path_for(request.kind)
    overrides_path = settings.overrides_path_for(request.kind)
    cache = load_cache(cache_path)
    overrides = load_overrides(overrides_path)

    confirmed: list[CacheEntry] = []
    missing: list[str] = []
    for dir_name in request.dir_names:
        entry = cache.entries.get(dir_name)
        if entry is None or entry.tmdb is None:
            missing.append(dir_name)
            continue
        overrides[dir_name] = entry.tmdb.id
        entry.source = "override"
        entry.match_confidence = 1.0
        entry.low_confidence = False
        confirmed.append(entry)

    if not confirmed:
        raise HTTPException(status_code=404, detail=f"Nothing to confirm: {missing}")

    save_overrides(overrides_path, overrides)
    save_cache(cache_path, cache)
    return confirmed


# Sync, not async: launching the file manager blocks briefly, and a `def` route runs
# in FastAPI's threadpool rather than stalling the event loop.
@app.post("/api/open")
def open_folder(request: OpenRequest) -> dict[str, str]:
    """Show a folder in the file manager of the machine running the server.

    Localhost-only, so that machine is the one whose browser did the clicking.
    """
    settings = get_settings()
    entry = read_cache(settings, request.kind).entries.get(request.dir_name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such folder: {request.dir_name}")

    target = Path(entry.path)
    if not under_any(entry.path, settings.library_dirs(request.kind)):
        raise HTTPException(
            status_code=403,
            detail=f"{target} is not inside a configured {request.kind} folder",
        )
    # An entry whose drive is unplugged stays in the cache on purpose (see run_sync),
    # so a path that is simply not there right now is the common failure here.
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{target} is not there right now — the drive may be disconnected.",
        )

    try:
        reveal(target)
    except RevealError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"path": str(target)}


def _mount_frontend() -> None:
    dist: Path = get_settings().frontend_dist
    if not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            # Without this, a typo'd or rejected API path silently returns the
            # app shell with a 200 instead of an error.
            raise HTTPException(status_code=404, detail=f"No such API route: /{full_path}")
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend()
