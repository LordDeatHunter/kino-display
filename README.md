# Movielister

A local web app that puts TMDB metadata — posters, plots, ratings, runtimes, cast — in front of a
folder-per-film movie library. Metadata is fetched once and cached on disk, so later runs only
touch TMDB for folders that are actually new.

FastAPI backend, SolidJS frontend, one JSON file for storage.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env      # then fill in your TMDB token
python main.py              # http://127.0.0.1:8000
```

`main.py` is the whole startup path: it works out where your library is, builds the web UI if
`frontend/dist` isn't there yet, and starts the server.

Every run starts by listing your movies folders, so you can see and extend them without editing
anything:

```
movies folders (from config.json):
  1. D:\Movies
  2. E:\Movies 2   (missing)
  [Enter]  open the picker and add another folder
  [Esc]    continue with these
```

**Esc** carries on with exactly what's listed and writes nothing. **Enter** opens a folder picker
and appends what you choose, then asks again — so you can add several in a row. Additions are
saved to `config.json`, which is created on the spot if this is the first run.

The list itself comes from `config.json`, or from `MOVIES_DIRS` in `.env` if there's no config
yet, or is empty on a machine where neither is set.

```json
{
  "movies_dirs": ["D:/Movies", "E:/Movies 2"]
}
```

The folders are scanned in order and merged into one library. The older singular `"movies_dir"`
key still works and is upgraded to the list on the next run. To remove or reorder folders, edit
`config.json` (or delete it to start over).

Then fetch metadata — once, and after that only for folders that are new:

```powershell
python manage.py sync
```

`.env` keys:

| key | meaning |
| --- | --- |
| `API_READ_ACCESS_TOKEN` | TMDB v4 bearer token — what the app uses |
| `API_KEY` | TMDB v3 key, used only if no bearer token is set |
| `MOVIES_DIRS` | your library folders, separated by `;` on Windows (`:` elsewhere) — normally set via `config.json`, which wins over `.env`. Set here it becomes the default the first-run prompt offers |
| `DATA_DIR` | where `cache.json` and `overrides.json` live (default `data`) |
| `HOST` / `PORT` | server bind address |
| `TMDB_LANGUAGE` / `MAX_CONCURRENCY` | metadata language, parallel request cap |

Settings are read from, highest priority first: real environment variables, `config.json`, `.env`.
Relative paths resolve from the project root.

## Use

```powershell
python main.py             # set up if needed, then serve on http://127.0.0.1:8000
python manage.py sync      # fetch metadata for new folders, drop deleted ones
python manage.py serve     # serve only, no setup or frontend build
```

### Commands

| command | what it does |
| --- | --- |
| `python manage.py scan -v` | parse folder names only — no API calls. Useful for checking the parser |
| `python manage.py sync` | the normal path: fetch new folders, forget deleted ones, leave the rest untouched |
| `python manage.py sync --force` | refetch every entry from scratch |
| `python manage.py sync --retry-unmatched` | retry only the entries that never matched |
| `python manage.py sync --only "Folder Name" ...` | force a refetch of specific folders |
| `python manage.py prefetch` | download all posters up front (`--backdrops`, `--cast`, `--all`) |
| `python manage.py status` | cache summary plus every unmatched / low-confidence entry |
| `python manage.py serve --reload` | dev server with auto-reload |

The **Sync**, **Retry unmatched** and **Force refetch** buttons in the UI do the same three things,
with a live progress bar.

### Browsing

Search covers title, original title, tagline, director, cast, genre and folder name. Sort by
title, year, rating, vote count, popularity, runtime, copies on disk or date added — each with an
ascending/descending toggle next to the picker. Choosing a field resets to its natural direction
(titles A→Z, everything else best or newest first); the toggle then flips it. Films with no value
for the chosen field always sort to the end, in either direction.

## How caching works

`data/cache.json` is keyed by folder name:

- folder in cache and still on disk → left alone, no API call
- folder on disk but not in cache → fetched
- folder in cache but gone from disk → dropped
- a renamed folder therefore reads as one removal plus one addition

Since the key is the folder name alone, the same name in two library folders is one entry: the
first folder listed in `config.json` wins and `python manage.py scan` prints the path it skipped.

A library folder that isn't there right now — an unplugged drive, say — is skipped with a note
instead of failing the scan, and its cached films stay in the cache rather than reading as several
hundred deletions. Only when *every* library folder is missing does a scan error out, since that's
a broken config rather than an offline disk.

Writes are atomic and checkpointed every 25 entries, so an interrupted sync never corrupts the
cache.

## Images

The browser never contacts `image.tmdb.org`. Artwork is requested from the backend at
`/api/img/{size}/{file}`, which serves it from `data/images/` or fetches it once and stores it
there. Responses carry `X-Cache: HIT|MISS` and a one-year immutable `Cache-Control`, since TMDB
paths are content-addressed.

This exists because hotlinking made every page load depend on `image.tmdb.org` resolving — one
DNS blip aborted all 300 poster requests at once and left the grid blank. Now a poster is fetched
at most once, ever.

```powershell
python manage.py prefetch          # ~284 posters, ~11 MB — the UI then works offline
python manage.py prefetch --all    # plus backdrops and cast portraits
```

`prefetch` skips anything already on disk, so re-running it is cheap. Images that can't be
fetched fall back to a placeholder card rather than a broken-image icon.

## Name matching

Folder names are stripped of bracket groups, resolutions, codecs, audio tags and release-group
suffixes, then reduced to a title and a year (`The.Fall.Guy.2024.1080p.AMZN...` → *The Fall Guy*,
2024). Search results are scored on title similarity plus a year bonus. When the best candidate
is weak the query is widened: dropping the year filter (a folder's year is often the rip's, not
the film's), de-leeting mixed letter/digit words (`VaCaTi0n` → `Vacation`), and stripping a
trailing roman numeral one (`SAW I` → `Saw`).

Anything the search can't place is cached as `unmatched` and flagged in the UI; matches below
0.75 confidence, or matches for folders with no year, are flagged as worth checking.

## Checking and fixing matches

Entries the matcher wasn't sure about get a `check` badge — matches below 0.75 confidence, or any
folder with no year in its name. Tick **Needs attention** in the toolbar to see just those.

Open one and the modal asks *"Is this the right film?"*:

- **✓ Looks right** — accepts the match. It gets pinned as an override, so the badge clears and no
  future sync (not even `--force`) can move it. No network needed.
- **Pick a different film** — searches TMDB and lets you choose the correct entry.

With the **Needs attention** filter on, an **Accept all N shown** button appears, which confirms
everything currently listed in one go. It only ever acts on what's on screen, so narrow the list
first (by genre or search) if you want to work through it in batches. Anything accepted by mistake
can be re-fixed individually afterwards.

Both paths write to `data/overrides.json` (see `overrides.example.json`), which you can also edit
by hand:

```json
{
  "Black Panther": 284054,
  "Some Boxset Folder": null
}
```

Keys are exact folder names, values are TMDB movie ids. `null` hides the folder from the UI.
Overrides win over search, survive `--force`, and take effect on the next sync.

## Development

```powershell
python manage.py serve --reload    # API on :8000
cd frontend && npm run dev         # UI on :5173, proxying /api to :8000
```

`npm run build` writes `frontend/dist`, which the FastAPI server mounts automatically — after a
build, `python manage.py serve` alone runs the whole app.

## Layout

```
main.py               start everything: config.json, frontend build, server
manage.py             CLI entry point
config.json           your library locations (gitignored, see config.example.json)
backend/app/
  config.py           settings from config.json and .env
  setup.py            first-run folder prompt and frontend build
  scanner.py          library scan + folder-name parsing
  tmdb.py             TMDB client and match scoring
  cache.py            atomic JSON persistence
  images.py           on-disk artwork store and prefetch
  sync.py             cache/disk diff and fetch orchestration
  main.py             FastAPI routes
  cli.py              scan / sync / status / serve
frontend/src/         SolidJS UI
data/                 cache.json, overrides.json, images/ (gitignored)
```
