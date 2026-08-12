import { For, Show, createMemo } from 'solid-js'
import type { MediaKind, SyncStatus } from '../types'
import type { SortDirection, SortMode } from '../util'

interface Props {
  kind: MediaKind
  query: string
  onQuery: (value: string) => void
  sort: SortMode
  onSort: (value: SortMode) => void
  direction: SortDirection
  onDirection: (value: SortDirection) => void
  genre: string
  onGenre: (value: string) => void
  genres: string[]
  issuesOnly: boolean
  onIssuesOnly: (value: boolean) => void
  confirmable: number
  onAcceptAll: () => void
  shown: number
  total: number
  issues: number
  syncedAt: string
  status: SyncStatus | null
  onSync: (mode: 'incremental' | 'force' | 'unmatched') => void
}

interface SortOption {
  value: SortMode
  label: string
  asc: string
  desc: string
  /** Absent means "both libraries". */
  only?: MediaKind
}

const SORTS: SortOption[] = [
  { value: 'title', label: 'Title', asc: 'A → Z', desc: 'Z → A' },
  { value: 'year', label: 'Year', asc: 'Oldest first', desc: 'Newest first' },
  { value: 'rating', label: 'Rating', asc: 'Lowest first', desc: 'Highest first' },
  { value: 'votes', label: 'Vote count', asc: 'Fewest first', desc: 'Most first' },
  { value: 'popularity', label: 'Popularity', asc: 'Least first', desc: 'Most first' },
  // A show's "runtime" is one episode's, which is not a useful thing to rank by.
  { value: 'runtime', label: 'Runtime', asc: 'Shortest first', desc: 'Longest first', only: 'movies' },
  { value: 'seasons', label: 'Seasons', asc: 'Fewest first', desc: 'Most first', only: 'series' },
  { value: 'copies', label: 'Copies on disk', asc: 'Fewest first', desc: 'Most first' },
  { value: 'added', label: 'Date added', asc: 'Oldest first', desc: 'Newest first' },
]

export default function Toolbar(props: Props) {
  const running = () => props.status?.running ?? false
  const sorts = createMemo(() => SORTS.filter((sort) => !sort.only || sort.only === props.kind))
  const noun = () => (props.kind === 'series' ? 'shows' : 'films')
  const directionLabel = () => {
    const sort = SORTS.find((entry) => entry.value === props.sort) ?? SORTS[0]
    return props.direction === 'asc' ? sort.asc : sort.desc
  }
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
            {props.shown === props.total
              ? `${props.total} ${noun()}`
              : `${props.shown} of ${props.total}`}
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
              if (
                confirm(
                  `Refetch metadata for every ${props.kind} folder? This re-queries TMDB for all entries.`,
                )
              ) {
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
          placeholder={
            props.kind === 'series'
              ? 'Search title, creator, cast, genre, folder…'
              : 'Search title, director, cast, genre, folder…'
          }
          value={props.query}
          onInput={(event) => props.onQuery(event.currentTarget.value)}
        />

        <div class="field">
          <label class="field-label" for="genre-filter">
            Genre
          </label>
          <select
            id="genre-filter"
            value={props.genre}
            onChange={(event) => props.onGenre(event.currentTarget.value)}
          >
            <option value="">All genres</option>
            <For each={props.genres}>{(genre) => <option value={genre}>{genre}</option>}</For>
          </select>
        </div>

        <div class="field">
          <label class="field-label" for="sort-field">
            Sort by
          </label>
          {/* Field and direction are joined into one control so it reads as a
              single "sort" widget rather than two unlabelled dropdowns. */}
          <div class="control-group">
            <select
              id="sort-field"
              value={props.sort}
              onChange={(event) => props.onSort(event.currentTarget.value as SortMode)}
            >
              <For each={sorts()}>{(sort) => <option value={sort.value}>{sort.label}</option>}</For>
            </select>
            <button
              type="button"
              class="sort-dir"
              title={`${directionLabel()} — click to reverse`}
              aria-label={`Sort direction: ${directionLabel()}. Click to reverse.`}
              onClick={() => props.onDirection(props.direction === 'asc' ? 'desc' : 'asc')}
            >
              <span class="sort-arrow">{props.direction === 'asc' ? '↑' : '↓'}</span>
              <span class="sort-dir-label">{directionLabel()}</span>
            </button>
          </div>
        </div>

        <label class="toggle">
          <input
            type="checkbox"
            checked={props.issuesOnly}
            onChange={(event) => props.onIssuesOnly(event.currentTarget.checked)}
          />
          Needs attention ({props.issues})
        </label>

        {/* Only offered while the flagged list is on screen, so it always acts
            on exactly what you can see. */}
        <Show when={props.issuesOnly && props.confirmable > 0}>
          <button type="button" class="accept-all" onClick={props.onAcceptAll}>
            ✓ Accept all {props.confirmable} shown
          </button>
        </Show>

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
