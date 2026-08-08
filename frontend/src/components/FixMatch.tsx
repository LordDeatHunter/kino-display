import { For, Show, createSignal } from 'solid-js'
import { clearOverride, searchTmdb, setOverride } from '../api'
import type { CacheEntry, SearchResult } from '../types'
import { imageUrl } from '../util'

interface Props {
  entry: CacheEntry
  onApplied: (entry: CacheEntry) => void
}

export default function FixMatch(props: Props) {
  const [query, setQuery] = createSignal(props.entry.parsed_title)
  const [results, setResults] = createSignal<SearchResult[]>([])
  const [busy, setBusy] = createSignal(false)
  const [message, setMessage] = createSignal('')

  const run = async (event: Event) => {
    event.preventDefault()
    const text = query().trim()
    if (!text) return
    setBusy(true)
    setMessage('')
    try {
      const payload = await searchTmdb(text)
      setResults(payload.results)
      if (!payload.results.length) setMessage('No results on TMDB for that title.')
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  const apply = async (tmdbId: number | null) => {
    setBusy(true)
    setMessage('')
    try {
      const updated = await setOverride(props.entry.dir_name, tmdbId)
      props.onApplied(updated)
      setResults([])
      setMessage(tmdbId === null ? 'Folder is now ignored.' : `Pinned to TMDB #${tmdbId}.`)
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    setBusy(true)
    try {
      const updated = await clearOverride(props.entry.dir_name)
      props.onApplied(updated)
      setMessage('Override removed — re-matched by search.')
    } catch (error) {
      setMessage(String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div class="fixmatch">
      <div class="fixmatch-head">
        <strong>Fix match</strong>
        <code class="folder">{props.entry.dir_name}</code>
      </div>

      <form class="fixmatch-form" onSubmit={run}>
        <input
          type="search"
          value={query()}
          onInput={(event) => setQuery(event.currentTarget.value)}
          placeholder="Search TMDB by title…"
        />
        <button type="submit" disabled={busy()}>
          Search
        </button>
        <button type="button" class="ghost" disabled={busy()} onClick={() => apply(null)}>
          Ignore folder
        </button>
        <Show when={props.entry.source === 'override'}>
          <button type="button" class="ghost" disabled={busy()} onClick={reset}>
            Clear override
          </button>
        </Show>
      </form>

      <Show when={message()}>
        <p class="fixmatch-msg">{message()}</p>
      </Show>

      <Show when={results().length}>
        <ul class="fixmatch-results">
          <For each={results()}>
            {(result) => (
              <li>
                <button type="button" disabled={busy()} onClick={() => apply(result.id)}>
                  <Show
                    when={imageUrl(result.poster_path, 'w92')}
                    fallback={<div class="thumb-empty" />}
                  >
                    {(src) => <img src={src()} alt="" loading="lazy" />}
                  </Show>
                  <span class="fixmatch-info">
                    <span class="fixmatch-title">
                      {result.title}
                      <span class="muted"> ({result.release_date?.slice(0, 4) || '—'})</span>
                    </span>
                    <span class="fixmatch-overview">{result.overview?.slice(0, 140)}</span>
                  </span>
                </button>
              </li>
            )}
          </For>
        </ul>
      </Show>
    </div>
  )
}
