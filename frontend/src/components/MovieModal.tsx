import { For, Show, createSignal, onCleanup, onMount } from 'solid-js'
import { confirmMatches } from '../api'
import type { CacheEntry, MovieGroup } from '../types'
import { entryNeedsAttention, formatRuntime, imageUrl } from '../util'
import FixMatch from './FixMatch'

interface Props {
  group: MovieGroup
  onClose: () => void
  onEntryUpdated: (entry: CacheEntry) => void
}

export default function MovieModal(props: Props) {
  const [showFix, setShowFix] = createSignal(false)
  const [posterBroken, setPosterBroken] = createSignal(false)
  const [confirming, setConfirming] = createSignal(false)
  const movie = () => props.group.tmdb

  const flagged = () => props.group.entries.filter(entryNeedsAttention)
  const worstConfidence = () =>
    Math.min(...props.group.entries.map((entry) => entry.match_confidence))

  const accept = async () => {
    setConfirming(true)
    try {
      const updated = await confirmMatches(flagged().map((entry) => entry.dir_name))
      updated.forEach(props.onEntryUpdated)
    } finally {
      setConfirming(false)
    }
  }

  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') props.onClose()
  }
  onMount(() => document.addEventListener('keydown', onKey))
  onCleanup(() => document.removeEventListener('keydown', onKey))

  const backdrop = () => imageUrl(movie()?.backdrop_path, 'w1280')
  const poster = () => (posterBroken() ? null : imageUrl(movie()?.poster_path, 'w342'))

  return (
    <div class="modal-backdrop" onClick={props.onClose}>
      <div class="modal" onClick={(event) => event.stopPropagation()}>
        <button class="modal-close" type="button" onClick={props.onClose} aria-label="Close">
          ✕
        </button>

        <Show when={backdrop()}>
          {(src) => (
            <div class="modal-hero" style={{ 'background-image': `url(${src()})` }}>
              <div class="modal-hero-fade" />
            </div>
          )}
        </Show>

        <div class="modal-body">
          <div class="modal-top">
            <Show when={poster()} fallback={<div class="modal-poster-empty">🎞</div>}>
              {(src) => (
                <img
                  class="modal-poster"
                  src={src()}
                  alt={props.group.title}
                  onError={() => setPosterBroken(true)}
                />
              )}
            </Show>

            <div class="modal-headings">
              <h2>{props.group.title}</h2>
              <Show when={movie()?.tagline}>
                <p class="tagline">{movie()!.tagline}</p>
              </Show>

              <p class="modal-facts">
                <Show when={props.group.year}>
                  <span>{props.group.year}</span>
                </Show>
                <Show when={props.group.runtime}>
                  <span>{formatRuntime(props.group.runtime)}</span>
                </Show>
                <Show when={props.group.rating > 0}>
                  <span>★ {props.group.rating.toFixed(1)} ({movie()?.vote_count ?? 0})</span>
                </Show>
                <Show when={movie()?.directors.length}>
                  <span>Dir. {movie()!.directors.join(', ')}</span>
                </Show>
              </p>

              <Show when={props.group.genres.length}>
                <p class="chips">
                  <For each={props.group.genres}>{(genre) => <span class="chip">{genre}</span>}</For>
                </p>
              </Show>

              <p class="modal-links">
                <Show when={movie()}>
                  <a href={`https://www.themoviedb.org/movie/${movie()!.id}`} target="_blank" rel="noreferrer">
                    TMDB
                  </a>
                </Show>
                <Show when={movie()?.imdb_id}>
                  <a href={`https://www.imdb.com/title/${movie()!.imdb_id}`} target="_blank" rel="noreferrer">
                    IMDb
                  </a>
                </Show>
                <button type="button" class="linklike" onClick={() => setShowFix((value) => !value)}>
                  {showFix() ? 'Hide match tools' : 'Wrong movie?'}
                </button>
              </p>
            </div>
          </div>

          <Show when={props.group.needsAttention}>
            <div class="verify">
              <div class="verify-text">
                <strong>Is this the right film?</strong>
                <Show
                  when={movie()}
                  fallback={<span>No TMDB match was found for this folder — search for it below.</span>}
                >
                  <span>
                    Picked automatically
                    {Number.isFinite(worstConfidence()) && worstConfidence() > 0
                      ? ` with ${(worstConfidence() * 100).toFixed(0)}% confidence`
                      : ''}
                    , so it's worth a glance. Accepting pins it — the flag clears and a
                    re-sync won't change it.
                  </span>
                </Show>
              </div>
              <div class="verify-actions">
                <Show when={movie()}>
                  <button type="button" disabled={confirming()} onClick={accept}>
                    {confirming() ? 'Accepting…' : '✓ Looks right'}
                  </button>
                </Show>
                <button
                  type="button"
                  class="ghost"
                  onClick={() => setShowFix((value) => !value)}
                >
                  {showFix() ? 'Hide search' : 'Pick a different film'}
                </button>
              </div>
            </div>
          </Show>

          <Show when={movie()?.overview}>
            <p class="overview">{movie()!.overview}</p>
          </Show>

          <Show when={movie()?.cast.length}>
            <section class="section">
              <h3>Cast</h3>
              <ul class="cast">
                <For each={movie()!.cast}>
                  {(member) => (
                    <li>
                      <Show
                        when={imageUrl(member.profile_path, 'w185')}
                        fallback={<div class="cast-empty">{member.name.slice(0, 1)}</div>}
                      >
                        {(src) => <img src={src()} alt="" loading="lazy" />}
                      </Show>
                      <span class="cast-name">{member.name}</span>
                      <span class="cast-role">{member.character}</span>
                    </li>
                  )}
                </For>
              </ul>
            </section>
          </Show>

          <section class="section">
            <h3>
              {props.group.entries.length > 1 ? `${props.group.entries.length} copies on disk` : 'On disk'}
            </h3>
            <ul class="paths">
              <For each={props.group.entries}>
                {(entry) => (
                  <li>
                    <code>{entry.path}</code>
                    <span class="path-meta">
                      matched as {entry.source} · confidence {entry.match_confidence.toFixed(2)}
                      <Show when={entry.low_confidence}> · low confidence</Show>
                      <Show when={entry.status !== 'matched'}> · {entry.status}</Show>
                    </span>
                  </li>
                )}
              </For>
            </ul>
          </section>

          <Show when={showFix()}>
            <section class="section">
              <For each={props.group.entries}>
                {(entry) => (
                  <FixMatch entry={entry} onApplied={props.onEntryUpdated} />
                )}
              </For>
            </section>
          </Show>
        </div>
      </div>
    </div>
  )
}
