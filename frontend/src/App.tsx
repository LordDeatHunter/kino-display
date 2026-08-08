import { For, Show, createMemo, createSignal, onCleanup } from 'solid-js'
import { createStore, produce } from 'solid-js/store'
import { fetchMovies, fetchSyncStatus, startSync } from './api'
import MovieCard from './components/MovieCard'
import MovieModal from './components/MovieModal'
import Toolbar from './components/Toolbar'
import type { CacheEntry, CacheFile, MovieGroup, SyncStatus } from './types'
import { DEFAULT_DIRECTION, groupEntries, searchMatches, sortGroups } from './util'
import type { SortDirection, SortMode } from './util'

const EMPTY: CacheFile = { schema_version: 1, synced_at: '', image_base_url: '', entries: {} }

export default function App() {
  const [cache, setCache] = createStore<CacheFile>(EMPTY)
  const [loaded, setLoaded] = createSignal(false)
  const [loadError, setLoadError] = createSignal('')

  const [query, setQuery] = createSignal('')
  const [sort, setSort] = createSignal<SortMode>('title')
  const [direction, setDirection] = createSignal<SortDirection>(DEFAULT_DIRECTION.title)

  // Picking a new field resets to its natural direction; the toggle then flips it.
  const chooseSort = (mode: SortMode) => {
    setSort(mode)
    setDirection(DEFAULT_DIRECTION[mode])
  }
  const [genre, setGenre] = createSignal('')
  const [issuesOnly, setIssuesOnly] = createSignal(false)
  const [selected, setSelected] = createSignal<string | null>(null)
  const [status, setStatus] = createSignal<SyncStatus | null>(null)

  let poller: number | undefined
  onCleanup(() => clearInterval(poller))

  const load = async () => {
    try {
      setCache(await fetchMovies())
      setLoadError('')
    } catch (error) {
      setLoadError(String(error))
    } finally {
      setLoaded(true)
    }
  }
  void load()

  const poll = () => {
    clearInterval(poller)
    poller = setInterval(async () => {
      try {
        const next = await fetchSyncStatus()
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
        await startSync({ force: mode === 'force', retryUnmatched: mode === 'unmatched' }),
      )
      poll()
    } catch (error) {
      setStatus({
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
  const selectedGroup = createMemo<MovieGroup | null>(() => {
    const key = selected()
    if (!key) return null
    return allGroups().find((group) => group.entries.some((entry) => entry.dir_name === key)) ?? null
  })

  return (
    <div class="app">
      <Toolbar
        query={query()}
        onQuery={setQuery}
        sort={sort()}
        onSort={chooseSort}
        direction={direction()}
        onDirection={setDirection}
        genre={genre()}
        onGenre={setGenre}
        genres={genres()}
        issuesOnly={issuesOnly()}
        onIssuesOnly={setIssuesOnly}
        shown={visible().length}
        total={allGroups().length}
        issues={issueCount()}
        syncedAt={cache.synced_at}
        status={status()}
        onSync={runSync}
      />

      <main>
        <Show when={loadError()}>
          <p class="notice error">Could not load the cache: {loadError()}</p>
        </Show>

        <Show when={loaded() && !allGroups().length && !loadError()}>
          <p class="notice">
            The cache is empty. Run <code>python manage.py sync</code>, or press <strong>Sync</strong> above.
          </p>
        </Show>

        <div class="grid">
          <For each={visible()}>
            {(group) => (
              <MovieCard group={group} onOpen={(chosen) => setSelected(chosen.entries[0].dir_name)} />
            )}
          </For>
        </div>

        <Show when={loaded() && allGroups().length > 0 && visible().length === 0}>
          <p class="notice">Nothing matches those filters.</p>
        </Show>
      </main>

      <Show when={selectedGroup()}>
        {(group) => (
          <MovieModal
            group={group()}
            onClose={() => setSelected(null)}
            onEntryUpdated={applyEntry}
          />
        )}
      </Show>
    </div>
  )
}
