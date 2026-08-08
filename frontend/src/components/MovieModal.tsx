import { For, Show, createSignal, onCleanup, onMount } from 'solid-js'
import type { CacheEntry, MovieGroup } from '../types'
import { formatRuntime, imageUrl } from '../util'
import FixMatch from './FixMatch'

interface Props {
  group: MovieGroup
  onClose: () => void
  onEntryUpdated: (entry: CacheEntry) => void
}

export default function MovieModal(props: Props) {
  const [showFix, setShowFix] = createSignal(props.group.needsAttention)
  const [posterBroken, setPosterBroken] = createSignal(false)
  const movie = () => props.group.tmdb

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
