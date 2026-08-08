import { For, Show } from 'solid-js'
import type { SyncStatus } from '../types'
import type { SortMode } from '../util'

interface Props {
  query: string
  onQuery: (value: string) => void
  sort: SortMode
  onSort: (value: SortMode) => void
  genre: string
  onGenre: (value: string) => void
  genres: string[]
  issuesOnly: boolean
  onIssuesOnly: (value: boolean) => void
  shown: number
  total: number
  issues: number
  syncedAt: string
  status: SyncStatus | null
  onSync: (mode: 'incremental' | 'force' | 'unmatched') => void
}

const SORTS: { value: SortMode; label: string }[] = [
  { value: 'title', label: 'Title' },
  { value: 'year', label: 'Year' },
  { value: 'rating', label: 'Rating' },
  { value: 'runtime', label: 'Runtime' },
  { value: 'added', label: 'Recently added' },
]

export default function Toolbar(props: Props) {
  const running = () => props.status?.running ?? false
  const percent = () => {
    const status = props.status
    if (!status || !status.total) return 0
    return Math.round((status.done / status.total) * 100)
  }

  return (
    <header class="toolbar">
      <div class="toolbar-row">
        <h1>
          Movielister
          <span class="count">
            {props.shown === props.total ? `${props.total} films` : `${props.shown} of ${props.total}`}
          </span>
        </h1>

        <div class="toolbar-actions">
          <button type="button" disabled={running()} onClick={() => props.onSync('incremental')}>
            Sync
          </button>
          <button
            type="button"
            class="ghost"
            disabled={running() || props.issues === 0}
            onClick={() => props.onSync('unmatched')}
          >
            Retry unmatched
          </button>
          <button
            type="button"
            class="ghost danger"
            disabled={running()}
            onClick={() => {
              if (confirm('Refetch metadata for every folder? This re-queries TMDB for all entries.')) {
                props.onSync('force')
              }
            }}
          >
            Force refetch
          </button>
        </div>
      </div>

      <div class="toolbar-row controls">
        <input
          class="search"
          type="search"
          placeholder="Search title, director, cast, genre, folder…"
          value={props.query}
          onInput={(event) => props.onQuery(event.currentTarget.value)}
        />

        <select value={props.genre} onChange={(event) => props.onGenre(event.currentTarget.value)}>
          <option value="">All genres</option>
          <For each={props.genres}>{(genre) => <option value={genre}>{genre}</option>}</For>
        </select>

        <select
          value={props.sort}
          onChange={(event) => props.onSort(event.currentTarget.value as SortMode)}
        >
          <For each={SORTS}>{(sort) => <option value={sort.value}>{sort.label}</option>}</For>
        </select>

        <label class="toggle">
          <input
            type="checkbox"
            checked={props.issuesOnly}
            onChange={(event) => props.onIssuesOnly(event.currentTarget.checked)}
          />
          Needs attention ({props.issues})
        </label>

        <span class="synced">
          <Show when={props.syncedAt} fallback="never synced">
            synced {props.syncedAt.replace('T', ' ').replace('+00:00', ' UTC')}
          </Show>
        </span>
      </div>

      <Show when={running() || props.status?.error}>
        <div class="progress">
          <Show
            when={!props.status?.error}
            fallback={<span class="progress-error">Sync failed: {props.status?.error}</span>}
          >
            <div class="progress-bar">
              <div class="progress-fill" style={{ width: `${percent()}%` }} />
            </div>
            <span class="progress-label">
              {props.status?.done ?? 0}/{props.status?.total ?? 0} · {props.status?.current}
            </span>
          </Show>
        </div>
      </Show>
    </header>
  )
}
