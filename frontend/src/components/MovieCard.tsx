import { Show, createMemo, createSignal } from 'solid-js'
import type { TitleGroup } from '../types'
import { imageUrl } from '../util'

interface Props {
  group: TitleGroup
  onOpen: (group: TitleGroup) => void
}

export default function MovieCard(props: Props) {
  const [broken, setBroken] = createSignal(false)
  // A failed poster should leave a readable card, not a broken-image icon.
  const poster = createMemo(() => (broken() ? null : imageUrl(props.group.tmdb?.poster_path, 'w342')))
  const seasons = () => props.group.tmdb?.number_of_seasons ?? 0

  return (
    <button class="card" onClick={() => props.onOpen(props.group)} type="button">
      <div class="card-poster">
        <Show
          when={poster()}
          fallback={
            <div class="poster-placeholder">
              <span class="poster-glyph">🎞</span>
              <span class="poster-name">{props.group.title}</span>
            </div>
          }
        >
          {(src) => (
            <img
              src={src()}
              alt={props.group.title}
              loading="lazy"
              decoding="async"
              onError={() => setBroken(true)}
            />
          )}
        </Show>

        <Show when={props.group.rating > 0}>
          <span class="badge badge-rating">{props.group.rating.toFixed(1)}</span>
        </Show>
        <Show when={props.group.entries.length > 1}>
          <span class="badge badge-copies">×{props.group.entries.length}</span>
        </Show>
        <Show when={props.group.needsAttention}>
          <span class="badge badge-warn" title="No match, or a low-confidence match">
            {props.group.tmdb ? 'check' : 'unmatched'}
          </span>
        </Show>
      </div>

      <div class="card-meta">
        <span class="card-title">{props.group.title}</span>
        <span class="card-sub">
          {props.group.year ?? '—'}
          <Show when={seasons()}>
            <span class="dot">·</span>
            {seasons()} season{seasons() === 1 ? '' : 's'}
          </Show>
          <Show when={props.group.genres.length}>
            <span class="dot">·</span>
            {props.group.genres[0]}
          </Show>
        </span>
      </div>
    </button>
  )
}
