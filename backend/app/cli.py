"""Command line entry point: scan, sync and serve."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .cache import load_cache
from .config import MEDIA_KINDS, MediaKind, get_settings
from .images import cached_files, prefetch
from .models import CacheEntry
from .scanner import scan_libraries
from .sync import run_sync


def _kinds(args: argparse.Namespace) -> list[MediaKind]:
    """The libraries a command should act on. `--kind all` is the default."""
    chosen = getattr(args, "kind", "all")
    return list(MEDIA_KINDS) if chosen == "all" else [chosen]


def _heading(kind: MediaKind, kinds: list[MediaKind]) -> None:
    """Only label sections when more than one library is in play."""
    if len(kinds) > 1:
        print(f"\n=== {kind} ===")


def _cmd_scan(args: argparse.Namespace) -> int:
    settings = get_settings()
    kinds = _kinds(args)
    for kind in kinds:
        _heading(kind, kinds)
        roots = settings.library_dirs(kind)
        if not roots:
            print(f"no {kind} folders configured")
            continue
        entries, notes = scan_libraries(roots, kind)
        missing_year = 0
        for entry in entries:
            if entry.parsed_year is None:
                missing_year += 1
            if args.verbose or entry.parsed_year is None or args.all:
                year = entry.parsed_year or "----"
                print(f"{year}  {entry.parsed_title:<50}  <- {entry.dir_name}")
        print(f"\n{len(entries)} entries ({missing_year} without a year) in:")
        for path in roots:
            print(f"  {path}")
        for note in notes:
            print(f"  {note}")
    return 0


def _print_progress(done: int, total: int, current: str) -> None:
    if total == 0:
        return
    bar_width = 28
    filled = int(bar_width * done / total)
    label = (current[:44] + "…") if len(current) > 45 else current
    sys.stdout.write(f"\r  [{'#' * filled}{'.' * (bar_width - filled)}] {done}/{total}  {label:<46}")
    sys.stdout.flush()
    if done == total:
        sys.stdout.write("\n")


def _cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.require_credentials()
    kinds = _kinds(args)
    for kind in kinds:
        _heading(kind, kinds)
        if not settings.library_dirs(kind):
            print(f"no {kind} folders configured — nothing to sync")
            continue
        report = asyncio.run(
            run_sync(
                settings,
                kind=kind,
                force=args.force,
                retry_unmatched=args.retry_unmatched,
                only=args.only or None,
                progress=_print_progress,
            )
        )
        print(
            f"\nfetched {report.fetched_count} "
            f"(new {len(report.added)}, refetched {len(report.refetched)})"
            f" · unchanged {report.unchanged} · removed {len(report.removed)}"
            f" · unmatched {report.unmatched} · errors {len(report.errors)}"
        )
        for name in report.removed:
            print(f"  removed: {name}")
        for problem in report.errors[:10]:
            print(f"  error:   {problem}")
        print(f"cache: {settings.cache_path_for(kind)}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    settings = get_settings()
    kinds = _kinds(args)
    for kind in kinds:
        _heading(kind, kinds)
        cache = load_cache(settings.cache_path_for(kind))
        entries: list[CacheEntry] = list(cache.entries.values())
        counts: dict[str, int] = {}
        for entry in entries:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        low = sum(1 for entry in entries if entry.low_confidence and entry.status == "matched")
        print(f"cache:     {settings.cache_path_for(kind)}")
        print(f"synced_at: {cache.synced_at or 'never'}")
        print(f"entries:   {len(entries)}")
        for status, count in sorted(counts.items()):
            print(f"  {status:<10} {count}")
        print(f"  low-confidence matches: {low}")
        if kind == "series":
            shows = [entry for entry in entries if entry.tmdb]
            episodes = sum(
                len(season.episodes) for entry in shows for season in entry.tmdb.seasons
            )
            seasons = sum(len(entry.tmdb.seasons) for entry in shows)
            print(f"  seasons cached: {seasons} · episodes cached: {episodes}")
        for entry in entries:
            if entry.status == "unmatched" or (entry.low_confidence and entry.status == "matched"):
                got = entry.tmdb.title if entry.tmdb else "—"
                print(f"    [{entry.match_confidence:.2f}] {entry.parsed_title!r} -> {got!r}  ({entry.dir_name})")
    return 0


def _cmd_prefetch(args: argparse.Namespace) -> int:
    settings = get_settings()
    kinds = _kinds(args)
    for kind in kinds:
        _heading(kind, kinds)
        downloaded, skipped, errors = asyncio.run(
            prefetch(
                settings,
                kind=kind,
                backdrops=args.backdrops or args.all,
                cast=args.cast or args.all,
                stills=args.stills or args.all,
                progress=_print_progress,
            )
        )
        print(f"\ndownloaded {downloaded} · already cached {skipped} · errors {len(errors)}")
        for problem in errors[:10]:
            print(f"  error: {problem}")
    count, total_bytes = cached_files(settings)
    print(f"store: {count} files, {total_bytes / 1_048_576:.1f} MB in {settings.images_dir}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="movielister", description="Local movie library browser")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_kind(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--kind",
            choices=("movies", "series", "all"),
            default="all",
            help="which library to act on (default: both)",
        )

    scan = sub.add_parser("scan", help="parse folder names without calling TMDB")
    scan.add_argument("-v", "--verbose", action="store_true", help="print every entry")
    scan.add_argument("--all", action="store_true", help="alias for --verbose")
    add_kind(scan)
    scan.set_defaults(func=_cmd_scan)

    sync = sub.add_parser("sync", help="fetch metadata for new folders (and drop deleted ones)")
    sync.add_argument("--force", action="store_true", help="refetch every entry")
    sync.add_argument("--retry-unmatched", action="store_true", help="refetch only entries that never matched")
    sync.add_argument("--only", nargs="*", metavar="FOLDER", help="refetch just these folder names")
    add_kind(sync)
    sync.set_defaults(func=_cmd_sync)

    fetch_images = sub.add_parser("prefetch", help="download artwork so the UI works offline")
    fetch_images.add_argument("--backdrops", action="store_true", help="also fetch modal backdrops")
    fetch_images.add_argument("--cast", action="store_true", help="also fetch cast portraits")
    fetch_images.add_argument("--stills", action="store_true", help="also fetch episode stills")
    fetch_images.add_argument("--all", action="store_true", help="posters, backdrops, cast and stills")
    add_kind(fetch_images)
    fetch_images.set_defaults(func=_cmd_prefetch)

    status = sub.add_parser("status", help="summarise the cache and list problem entries")
    add_kind(status)
    status.set_defaults(func=_cmd_status)

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
