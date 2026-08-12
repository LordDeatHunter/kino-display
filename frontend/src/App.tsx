import { For, Show, createEffect, createMemo, createSignal, onCleanup } from 'solid-js'
import { createStore, produce } from 'solid-js/store'
import { confirmMatches, fetchLibrary, fetchStats, fetchSyncStatus, startSync } from './api'
import MovieCard from './components/MovieCard'
import MovieModal from './components/MovieModal'
import Tabs from './components/Tabs'
import Toolbar from './components/Toolbar'
import type { CacheEntry, CacheFile, MediaKind, SyncStatus, TitleGroup } from './types'
import { DEFAULT_DIRECTION, confirmableEntries, groupEntries, searchMatches, sortGroups } from './util'
import type { SortDirection, SortMode } from './util'

const EMPTY: CacheFile = { schema_version: 1, synced_at: '', image_base_url: '', entries: {} }

const NOUN: Record<MediaKind, string> = { movies: 'film', series: 'show' }

const kindFromHash = (): MediaKind =>
  window.location.hash.replace(/^#\/?/, '') === 'series' ? 'series' : 'movies'

/** Everything one tab owns: its cache, its filters and its sync state.
 *
 *  Held per kind rather than reset on a switch, so flipping between tabs keeps
 *  your search, sort and scroll position on each. */
function createLibrary(kind: MediaKind) {
  const [cache, setCache] = createStore<CacheFile>({ ...EMPTY })
  const [loaded, setLoaded] = createSignal(false)
  const [loadError, setLoadError] = createSignal('')
  const [configured, setConfigured] = createSignal(true)
  const [status, setStatus] = createSignal<SyncStatus | null>(null)

  const [query, setQuery] = createSignal('')
  const [sort, setSort] = createSignal<SortMode>('title')
  const [direction, setDirection] = createSignal<SortDirection>(DEFAULT_DIRECTION.title)
  const [genre, setGenre] = createSignal('')
  const [issuesOnly, setIssuesOnly] = createSignal(false)
  const [selected, setSelected] = createSignal<string | null>(null)

  let poller: number | undefined
  let requested = false
  onCleanup(() => clearInterval(poller))

  const load = async () => {
    try {
      setCache(await fetchLibrary(kind))
      setLoadError('')
    } catch (error) {
      setLoadError(String(error))
    } finally {
      setLoaded(true)
    }
    // Only used to tell "nothing synced yet" apart from "no folders set up".
    try {
      setConfigured((await fetchStats(kind)).dirs.length > 0)
    } catch {
      setConfigured(true)
    }
  }

  /** Fetch on the tab's first visit, not on page load. */
  const ensureLoaded = () => {
    if (requested) return
    requested = true
    void load()
  }

  const poll = () => {
    clearInterval(poller)
    poller = setInterval(async () => {
      try {
        const next = await fetchSyncStatus(kind)
        setStatus(next)
        if (!next.running) {
          clearInterval(poller)
          await load()
        }
      } catch (error) {
        setStatus({ ...(status() as SyncStatus), running: false, error: String(error) })
        clearInterval(poller)
      }
    }, 700) as unknown as number
  }

  const runSync = async (mode: 'incremental' | 'force' | 'unmatched') => {
    try {
      setStatus(
        await startSync(kind, { force: mode === 'force', retryUnmatched: mode === 'unmatched' }),
      )
      poll()
    } catch (error) {
      setStatus({
        kind,
        running: false,
        total: 0,
        done: 0,
        current: '',
        started_at: '',
        finished_at: '',
        report: null,
        error: String(error),
      })
    }
  }

  const applyEntry = (entry: CacheEntry) => {
    setCache(produce((draft) => {
      draft.entries[entry.dir_name] = entry
    }))
  }

  const allGroups = createMemo(() => groupEntries(Object.values(cache.entries)))

  const genres = createMemo(() => {
    const names = new Set<string>()
    for (const group of allGroups()) group.genres.forEach((name) => names.add(name))
    return [...names].sort()
  })

  const issueCount = createMemo(() => allGroups().filter((group) => group.needsAttention).length)

  const visible = createMemo(() => {
    const chosenGenre = genre()
    const filtered = allGroups().filter((group) => {
      if (issuesOnly() && !group.needsAttention) return false
      if (chosenGenre && !group.genres.includes(chosenGenre)) return false
      return searchMatches(group, query())
    })
    return sortGroups(filtered, sort(), direction())
  })

  // Re-derive from the store so the modal reflects a fix applied inside it.
  const selectedGroup = createMemo<TitleGroup | null>(() => {
    const key = selected()
    if (!key) return null
    return allGroups().find((group) => group.entries.some((entry) => entry.dir_name === key)) ?? null
  })

  const acceptAllShown = async () => {
    const names = confirmableEntries(visible())
    if (!names.length) return
    const message =
      `Accept the current match for ${names.length} folder${names.length === 1 ? '' : 's'}?\n\n` +
      `Each one gets pinned to the ${NOUN[kind]} it already shows, so the flag clears and a ` +
      `re-sync won't change it. You can still fix any of them individually afterwards.`
    if (!confirm(message)) return
    try {
      const updated = await confirmMatches(names, kind)
      updated.forEach(applyEntry)
    } catch (error) {
      setLoadError(String(error))
    }
  }

  // Picking a new field resets to its natural direction; the toggle then flips it.
  const chooseSort = (mode: SortMode) => {
    setSort(mode)
    setDirection(DEFAULT_DIRECTION[mode])
  }

  return {
    cache,
    loaded,
    loadError,
    configured,
    status,
    query,
    setQuery,
    sort,
    chooseSort,
    direction,
    setDirection,
    genre,
    setGenre,
    genres,
    issuesOnly,
    setIssuesOnly,
    setSelected,
    allGroups,
    visible,
    issueCount,
    selectedGroup,
    ensureLoaded,
    runSync,
    applyEntry,
    acceptAllShown,
  }
}

export default function App() {
  const [kind, setKind] = createSignal<MediaKind>(kindFromHash())

  const libraries: Record<MediaKind, ReturnType<typeof createLibrary>> = {
    movies: createLibrary('movies'),
    series: createLibrary('series'),
  }
  const library = () => libraries[kind()]

  // The hash keeps the tab across a refresh, and the back button works.
  const onHashChange = () => setKind(kindFromHash())
  window.addEventListener('hashchange', onHashChange)
  onCleanup(() => window.removeEventListener('hashchange', onHashChange))

  const chooseKind = (next: MediaKind) => {
    window.location.hash = next === 'movies' ? '' : '#/series'
    setKind(next)
  }

  // Loads the movies tab now and the series tab the first time it is opened.
  createEffect(() => library().ensureLoaded())

  const counts = createMemo(() => ({
    movies: libraries.movies.loaded() ? libraries.movies.allGroups().length : undefined,
    series: libraries.series.loaded() ? libraries.series.allGroups().length : undefined,
  }))

  return (
    <div class="app">
      <Tabs kind={kind()} onKind={chooseKind} counts={counts()} />

      <Toolbar
        kind={kind()}
        query={library().query()}
        onQuery={library().setQuery}
        sort={library().sort()}
        onSort={library().chooseSort}
        direction={library().direction()}
        onDirection={library().setDirection}
        genre={library().genre()}
        onGenre={library().setGenre}
        genres={library().genres()}
        issuesOnly={library().issuesOnly()}
        onIssuesOnly={library().setIssuesOnly}
        confirmable={confirmableEntries(library().visible()).length}
        onAcceptAll={library().acceptAllShown}
        shown={library().visible().length}
        total={library().allGroups().length}
        issues={library().issueCount()}
        syncedAt={library().cache.synced_at}
        status={library().status()}
        onSync={library().runSync}
      />

      <main>
        <Show when={library().loadError()}>
          <p class="notice error">Could not load the cache: {library().loadError()}</p>
        </Show>

        <Show when={library().loaded() && !library().allGroups().length && !library().loadError()}>
          <Show
            when={library().configured()}
            fallback={
              <p class="notice">
                No {kind()} folders are set up yet. Run <code>python main.py</code>, open{' '}
                <strong>{kind() === 'series' ? 'Series' : 'Movies'}</strong> and add one.
              </p>
            }
          >
            <p class="notice">
              Nothing cached yet. Run <code>python manage.py sync --kind {kind()}</code>, or press{' '}
              <strong>Sync</strong> above.
            </p>
          </Show>
        </Show>

        <div class="grid">
          <For each={library().visible()}>
            {(group) => (
              <MovieCard
                group={group}
                onOpen={(chosen) => library().setSelected(chosen.entries[0].dir_name)}
              />
            )}
          </For>
        </div>

        <Show
          when={library().loaded() && library().allGroups().length > 0 && !library().visible().length}
        >
          <p class="notice">Nothing matches those filters.</p>
        </Show>
      </main>

      <Show when={library().selectedGroup()}>
        {(group) => (
          <MovieModal
            group={group()}
            kind={kind()}
            onClose={() => library().setSelected(null)}
            onEntryUpdated={library().applyEntry}
          />
        )}
      </Show>
    </div>
  )
}
