"""FastAPI application: serves the cached library and drives syncs."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cache import load_overrides, save_overrides
from .config import get_settings
from .images import ImageError, ImageNotFound, fetch_image
from .models import CacheEntry, CacheFile, OverrideRequest, SyncStatus
from .sync import read_cache, resolve_single, run_sync
from .tmdb import TmdbClient, TmdbError

app = FastAPI(title="Movielister", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_status = SyncStatus()
_sync_lock = asyncio.Lock()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@app.get("/api/movies", response_model=CacheFile)
def get_movies() -> CacheFile:
    return read_cache(get_settings())


@app.get("/api/stats")
def get_stats() -> dict[str, object]:
    cache = read_cache(get_settings())
    entries = list(cache.entries.values())
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return {
        "total": len(entries),
        "by_status": counts,
        "low_confidence": sum(1 for e in entries if e.low_confidence and e.status == "matched"),
        "synced_at": cache.synced_at,
        "movies_dir": str(get_settings().movies_dir),
    }


async def _run_sync_job(force: bool, retry_unmatched: bool) -> None:
    def progress(done: int, total: int, current: str) -> None:
        _status.done = done
        _status.total = total
        _status.current = current

    try:
        _status.report = await run_sync(
            get_settings(), force=force, retry_unmatched=retry_unmatched, progress=progress
        )
        _status.error = None
    except Exception as exc:  # surfaced to the UI rather than lost in the server log
        _status.error = f"{type(exc).__name__}: {exc}"
    finally:
        _status.running = False
        _status.finished_at = _now()
        _sync_lock.release()


@app.post("/api/sync", response_model=SyncStatus)
async def start_sync(
    force: bool = Query(False),
    retry_unmatched: bool = Query(False),
) -> SyncStatus:
    if _sync_lock.locked():
        raise HTTPException(status_code=409, detail="A sync is already running")
    await _sync_lock.acquire()

    _status.running = True
    _status.done = 0
    _status.total = 0
    _status.current = ""
    _status.started_at = _now()
    _status.finished_at = ""
    _status.report = None
    _status.error = None

    asyncio.create_task(_run_sync_job(force, retry_unmatched))
    return _status


@app.get("/api/sync/status", response_model=SyncStatus)
def sync_status() -> SyncStatus:
    return _status


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
async def tmdb_search(q: str = Query(min_length=1), year: int | None = None) -> dict[str, object]:
    settings = get_settings()
    try:
        async with TmdbClient(settings) as client:
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
    overrides = load_overrides(settings.overrides_path)
    overrides[request.dir_name] = request.tmdb_id
    save_overrides(settings.overrides_path, overrides)

    entry = await resolve_single(settings, request.dir_name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such folder: {request.dir_name}")
    return entry


@app.delete("/api/overrides/{dir_name:path}", response_model=CacheEntry)
async def clear_override(dir_name: str) -> CacheEntry:
    settings = get_settings()
    overrides = load_overrides(settings.overrides_path)
    overrides.pop(dir_name, None)
    save_overrides(settings.overrides_path, overrides)

    entry = await resolve_single(settings, dir_name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No such folder: {dir_name}")
    return entry


@app.get("/api/overrides")
def get_overrides() -> dict[str, int | None]:
    return load_overrides(get_settings().overrides_path)


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
