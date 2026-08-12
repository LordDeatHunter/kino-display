# Movielister

A local web app that puts TMDB metadata — posters, plots, ratings, runtimes, cast — in front of a
folder-per-title library. Metadata is fetched once and cached on disk, so later runs only touch
TMDB for folders that are actually new.

Two libraries live side by side, one per tab in the UI: **Movies** and **Series**. They are kept
completely apart — their own folders, their own cache, their own overrides — so syncing one can
never disturb the other. Shows carry their full season and episode list, browsable in the modal.

FastAPI backend, SolidJS frontend, one JSON file per library for storage.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env      # then fill in your TMDB token
python main.py              # http://127.0.0.1:8000
```

`main.py` is the whole startup path: it shows the launcher, builds the web UI if `frontend/dist`
isn't there yet, and starts the server.

## The launcher

`python main.py` opens a menu:

```
  movielister

  Movies      2 sources
  Series      no sources yet
  Start       launch the web app
```

- **↑/↓** move, **Enter** opens. **Movies** and **Series** each open a list of that library's
  folders.
- **Esc** on the main menu quits without starting anything.

Inside a library's screen:

```
  Series sources
  saved in config.json

  D:\Series
  E:\Series 2   (missing)

  [A] Add source   [D] Remove selected   [Esc] Back
```

**A** opens the OS folder picker (the TUI steps aside while it's up) and appends what you choose.
**D** removes the highlighted folder. **Esc** goes back. Every change is written to `config.json`
immediately — there's no save step.

The starting list comes from `config.json`, or from `MOVIES_DIRS` / `SERIES_DIRS` in `.env` if the
config has nothing for that library, or is empty when neither is set.

```json
{
  "movies_dirs": ["D:/Movies", "E:/Movies 2"],
  "series_dirs": ["D:/Series"]
}
```

Each library's folders are scanned in order and merged. The older singular `"movies_dir"` key
still works and is upgraded to the list on the next run. You can also edit `config.json` by hand
(or delete it to start over).

Without a terminal — a piped or scheduled run — the menu is skipped and the server starts with
whatever `config.json` already says.

Then fetch metadata — once, and after that only for folders that are new:

```powershell
python manage.py sync
```

`.env` keys:

| key | meaning |
| --- | --- |
| `API_READ_ACCESS_TOKEN` | TMDB v4 bearer token — what the app uses |
| `API_KEY` | TMDB v3 key, used only if no bearer token is set |
| `MOVIES_DIRS` | your film folders, separated by `;` on Windows (`:` elsewhere) — normally set via `config.json`, which wins over `.env`. Set here it becomes the fallback the launcher offers |
| `SERIES_DIRS` | the same, for your TV libraries |
| `DATA_DIR` | where the caches and overrides live (default `data`) |
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
| `python manage.py prefetch` | download all posters up front (`--backdrops`, `--cast`, `--stills`, `--all`) |
| `python manage.py status` | cache summary plus every unmatched / low-confidence entry |
| `python manage.py serve --reload` | dev server with auto-reload |

`scan`, `sync`, `prefetch` and `status` all take `--kind movies|series|all` and default to `all`,
so a bare `python manage.py sync` brings both libraries up to date.

The **Sync**, **Retry unmatched** and **Force refetch** buttons in the UI do the same three things
for whichever tab you're on, with a live progress bar. The two tabs sync independently — you can
start a series sync while a film sync is still running.

### Browsing

The **Movies** and **Series** tabs at the top of the page each keep their own search, sort and
filters, so switching between them doesn't lose your place. The tab lives in the URL hash
(`#/series`), so a refresh or a bookmark comes back to the same one.

Search covers title, original title, tagline, director or creator, cast, genre and folder name.
Sort by title, year, rating, vote count, popularity, copies on disk or date added — plus runtime
on Movies and season count on Series — each with an ascending/descending toggle next to the
picker. Choosing a field resets to its natural direction
(titles A→Z, everything else best or newest first); the toggle then flips it. Films with no value
for the chosen field always sort to the end, in either direction.

### Series

A series folder is one show — `D:\Series\Breaking Bad (2008)`, `D:\Series\The.Office.US.S01-S09`.
Only that top level is scanned; seasons and episodes come from TMDB, not from what's on disk, so
however you arrange the files inside doesn't matter.

Folder names go through the same parser as films, with season and pack markers stripped first
(`S01`, `S01-S09`, `S01E02`, `Season 3`, `Complete Series`). Matching then uses TMDB's TV search,
and a matched show pulls in every season with its full episode list — name, air date, runtime,
rating, overview and still. Open a show and the **Seasons** section expands one season at a time.

That means a series sync is slower than a film one: a show costs one request plus one per season,
against one flat request per film.

## How caching works

Each library has its own pair of files — `data/cache.json` + `data/overrides.json` for films,
`data/cache-series.json` + `data/overrides-series.json` for shows. They never mix.

A cache is keyed by folder name:

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
python manage.py prefetch --all    # plus backdrops, cast portraits and episode stills
```

Season posters come down with the posters; episode stills are behind `--stills` (or `--all`),
since a long-running show has hundreds of them.

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

Both paths write to that library's overrides file — `data/overrides.json` for films,
`data/overrides-series.json` for shows (see `overrides.example.json`) — which you can also edit by
hand:

```json
{
  "Black Panther": 284054,
  "Some Boxset Folder": null
}
```

Keys are exact folder names, values are TMDB ids — movie ids in the films file, TV ids in the
series one. `null` hides the folder from the UI. Overrides win over search, survive `--force`,
and take effect on the next sync.

## Development

```powershell
python manage.py serve --reload    # API on :8000
cd frontend && npm run dev         # UI on :5173, proxying /api to :8000
```

`npm run build` writes `frontend/dist`, which the FastAPI server mounts automatically — after a
build, `python manage.py serve` alone runs the whole app.

## Layout

```
main.py               start everything: launcher, frontend build, server
manage.py             CLI entry point
config.json           your library locations (gitignored, see config.example.json)
backend/app/
  config.py           settings from config.json and .env; the movies/series split
  setup.py            config.json helpers, folder picker and frontend build
  tui.py              the launcher menu (Textual)
  scanner.py          library scan + folder-name parsing
  tmdb.py             TMDB client (film and TV) and match scoring
  cache.py            atomic JSON persistence
  images.py           on-disk artwork store and prefetch
  sync.py             cache/disk diff and fetch orchestration
  main.py             FastAPI routes
  cli.py              scan / sync / status / serve
frontend/src/         SolidJS UI
data/                 cache.json, cache-series.json, overrides*.json, images/ (gitignored)
```
