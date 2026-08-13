import { For, Show, createMemo, createSignal, onCleanup, onMount } from 'solid-js'
import { confirmMatches, openFolder } from '../api'
import type { CacheEntry, MediaKind, TitleGroup } from '../types'
import {
  copyText,
  entryNeedsAttention,
  formatRuntime,
  imageUrl,
  parsedYearSpread,
  yearOf,
} from '../util'
import FixMatch from './FixMatch'

interface Props {
  group: TitleGroup
  kind: MediaKind
  onClose: () => void
  onEntryUpdated: (entry: CacheEntry) => void
}

export default function MovieModal(props: Props) {
  // The folder whose search form is open — one at a time, so several copies of the same
  // title can't present a row of identical-looking forms.
  const [fixing, setFixing] = createSignal<string | null>(null)
  const [note, setNote] = createSignal('')
  const [posterBroken, setPosterBroken] = createSignal(false)
  const [confirming, setConfirming] = createSignal(false)
  const [openSeason, setOpenSeason] = createSignal<number | null>(null)
  // The copy whose folder is being opened, so only that row's button greys out.
  const [opening, setOpening] = createSignal<string | null>(null)
  // Set only when a note is about a folder that would not open: the path the Copy
  // button offers, and the reason the note is styled as a warning.
  const [failedPath, setFailedPath] = createSignal<string | null>(null)
  const [copied, setCopied] = createSignal(false)
  const movie = () => props.group.tmdb
  const isShow = () => movie()?.media_type === 'tv'
  const noun = () => (props.kind === 'series' ? 'show' : 'film')
  let disk: HTMLElement | undefined

  const flagged = () => props.group.entries.filter(entryNeedsAttention)
  const worstConfidence = () =>
    Math.min(...props.group.entries.map((entry) => entry.match_confidence))
  const yearSpread = createMemo(() => parsedYearSpread(props.group.entries))

  const accept = async () => {
    setConfirming(true)
    try {
      const updated = await confirmMatches(
        flagged().map((entry) => entry.dir_name),
        props.kind,
      )
      updated.forEach(props.onEntryUpdated)
    } finally {
      setConfirming(false)
    }
  }

  const acceptOne = async (entry: CacheEntry) => {
    setConfirming(true)
    try {
      const updated = await confirmMatches([entry.dir_name], props.kind)
      updated.forEach(props.onEntryUpdated)
    } finally {
      setConfirming(false)
    }
  }

  /** A reassigned copy leaves this group, taking its row — and any message inside the
   *  form — with it, so the modal is the only thing left to explain where it went. */
  const applied = (entry: CacheEntry) => {
    // Read everything BEFORE the update: once the group has emptied, <Show>'s non-keyed
    // accessor throws a stale read on props.group.
    const before = props.group.entries.find((item) => item.dir_name === entry.dir_name)
    const leaving = !!before?.tmdb && entry.tmdb?.id !== before.tmdb.id
    const cardSurvives = props.group.entries.some(
      (item) => item.dir_name !== entry.dir_name && item.status !== 'ignored',
    )

    props.onEntryUpdated(entry)

    if (!leaving) return
    setFixing(null)
    if (!cardSurvives) return // the modal followed the move — there is nothing to explain
    // The year is not decoration: a remake shares its original's title, so without it the
    // note names the very card you are still looking at.
    const moved = yearOf(entry) ? `“${entry.tmdb?.title}” (${yearOf(entry)})` : `“${entry.tmdb?.title}”`
    setFailedPath(null) // this note is not about a folder that would not open
    setNote(
      entry.status === 'ignored'
        ? `${entry.dir_name} is ignored now and has dropped out of the library.`
        : `${entry.dir_name} is now ${moved} — it has its own card.`,
    )
  }

  const dismissNote = () => {
    setNote('')
    setFailedPath(null)
  }

  /** Ask the server's desktop to show this copy on disk. The browser cannot do it
   *  itself, and for a localhost-only app that desktop is this one. */
  const showOnDisk = async (entry: CacheEntry) => {
    setOpening(entry.dir_name)
    dismissNote()
    setCopied(false)
    try {
      await openFolder(entry.dir_name, props.kind)
    } catch (error) {
      // The path goes in the note, not just the reason: if the server opened it on
      // some other machine, copying it is the only thing left that helps.
      setFailedPath(entry.path)
      setNote(String(error).replace(/^Error:\s*/, ''))
    } finally {
      setOpening(null)
    }
  }

  const copyFailedPath = async () => {
    const path = failedPath()
    if (path) setCopied(await copyText(path))
  }

  /** One copy: open its form. Several: scroll to the list, which is the copy picker. */
  const openFix = () => {
    const entries = props.group.entries
    if (entries.length === 1) setFixing((open) => (open ? null : entries[0].dir_name))
    else disk?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  /** Same split as openFix: with one copy there is nothing to choose between, with
   *  several the copies list is the picker. */
  const openFolderFromHeader = () => {
    const entries = props.group.entries
    if (entries.length === 1) void showOnDisk(entries[0])
    else disk?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  /** With one copy the links toggle a form and should say so; with several they only
   *  scroll to the list, where each row carries its own label. */
  const fixLabel = (closed: string, open: string) =>
    props.group.entries.length === 1 && fixing() ? open : closed

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
                <Show when={isShow() && movie()?.number_of_seasons}>
                  <span>
                    {movie()!.number_of_seasons} season{movie()!.number_of_seasons === 1 ? '' : 's'}
                    <Show when={movie()?.number_of_episodes}>
                      {' · '}
                      {movie()!.number_of_episodes} episodes
                    </Show>
                  </span>
                </Show>
                <Show when={props.group.runtime}>
                  <span>
                    {formatRuntime(props.group.runtime)}
                    {isShow() ? ' / ep' : ''}
                  </span>
                </Show>
                <Show when={props.group.rating > 0}>
                  <span>★ {props.group.rating.toFixed(1)} ({movie()?.vote_count ?? 0})</span>
                </Show>
                <Show when={movie()?.directors.length}>
                  <span>
                    {isShow() ? 'Created by ' : 'Dir. '}
                    {movie()!.directors.join(', ')}
                  </span>
                </Show>
                <Show when={isShow() && movie()?.networks.length}>
                  <span>{movie()!.networks.join(', ')}</span>
                </Show>
              </p>

              <Show when={props.group.genres.length}>
                <p class="chips">
                  <For each={props.group.genres}>{(genre) => <span class="chip">{genre}</span>}</For>
                </p>
              </Show>

              <p class="modal-links">
                <Show when={movie()}>
                  <a
                    href={`https://www.themoviedb.org/${isShow() ? 'tv' : 'movie'}/${movie()!.id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    TMDB
                  </a>
                </Show>
                <Show when={movie()?.imdb_id}>
                  <a href={`https://www.imdb.com/title/${movie()!.imdb_id}`} target="_blank" rel="noreferrer">
                    IMDb
                  </a>
                </Show>
                <button type="button" class="linklike" onClick={openFolderFromHeader}>
                  📂 {props.group.entries.length === 1 ? 'Folder' : 'Folders'}
                </button>
                <button type="button" class="linklike" onClick={openFix}>
                  {fixLabel(`Wrong ${noun()}?`, 'Hide match tools')}
                </button>
              </p>
            </div>
          </div>

          <Show when={note()}>
            <p class="inline-note" classList={{ warn: !!failedPath() }}>
              {note()}
              <Show when={failedPath()}>
                <button type="button" class="linklike" onClick={copyFailedPath}>
                  {copied() ? 'Copied' : 'Copy path'}
                </button>
              </Show>
              <button type="button" class="linklike" onClick={dismissNote}>
                Dismiss
              </button>
            </p>
          </Show>

          <Show when={props.group.needsAttention}>
            <div class="verify">
              <div class="verify-text">
                <strong>Is this the right {noun()}?</strong>
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
                    <Show when={yearSpread().length > 1}>
                      {' '}
                      These copies are labelled with different years — check them one at a
                      time below.
                    </Show>
                  </span>
                </Show>
              </div>
              <div class="verify-actions">
                <Show when={movie()}>
                  <button type="button" disabled={confirming()} onClick={accept}>
                    {confirming()
                      ? 'Accepting…'
                      : flagged().length > 1
                        ? `✓ All ${flagged().length} copies are this ${noun()}`
                        : '✓ Looks right'}
                  </button>
                </Show>
                <button type="button" class="ghost" onClick={openFix}>
                  {fixLabel(`Pick a different ${noun()}`, 'Hide search')}
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

          <Show when={movie()?.seasons.length}>
            <section class="section">
              <h3>Seasons</h3>
              {/* One season open at a time — a long-running show is otherwise
                  hundreds of episodes of scrolling. */}
              <ul class="seasons">
                <For each={movie()!.seasons}>
                  {(season) => {
                    const open = () => openSeason() === season.season_number
                    return (
                      <li classList={{ open: open() }}>
                        <button
                          type="button"
                          class="season-head"
                          aria-expanded={open()}
                          onClick={() =>
                            setOpenSeason(open() ? null : season.season_number)
                          }
                        >
                          <Show
                            when={imageUrl(season.poster_path, 'w185')}
                            fallback={<div class="season-poster-empty">📺</div>}
                          >
                            {(src) => <img class="season-poster" src={src()} alt="" loading="lazy" />}
                          </Show>
                          <span class="season-info">
                            <span class="season-name">{season.name}</span>
                            <span class="season-meta">
                              <Show when={season.air_date}>{season.air_date.slice(0, 4)} · </Show>
                              {season.episode_count} episode{season.episode_count === 1 ? '' : 's'}
                            </span>
                            <Show when={season.overview}>
                              <span class="season-overview">{season.overview}</span>
                            </Show>
                          </span>
                          <span class="season-chevron">{open() ? '▾' : '▸'}</span>
                        </button>

                        <Show when={open()}>
                          <ul class="episodes">
                            <For each={season.episodes}>
                              {(episode) => (
                                <li>
                                  <Show
                                    when={imageUrl(episode.still_path, 'w300')}
                                    fallback={<div class="still-empty" />}
                                  >
                                    {(src) => <img class="still" src={src()} alt="" loading="lazy" />}
                                  </Show>
                                  <div class="episode-info">
                                    <span class="episode-title">
                                      {episode.episode_number}. {episode.name}
                                    </span>
                                    <span class="episode-meta">
                                      <Show when={episode.air_date}>{episode.air_date}</Show>
                                      <Show when={episode.runtime}>
                                        {' · '}
                                        {formatRuntime(episode.runtime)}
                                      </Show>
                                      <Show when={episode.vote_average > 0}>
                                        {' · ★ '}
                                        {episode.vote_average.toFixed(1)}
                                      </Show>
                                    </span>
                                    <Show when={episode.overview}>
                                      <p class="episode-overview">{episode.overview}</p>
                                    </Show>
                                  </div>
                                </li>
                              )}
                            </For>
                            <Show when={!season.episodes.length}>
                              <li class="muted">No episode details cached for this season.</li>
                            </Show>
                          </ul>
                        </Show>
                      </li>
                    )
                  }}
                </For>
              </ul>
            </section>
          </Show>

          <section class="section" ref={disk}>
            <h3>
              {props.group.entries.length > 1 ? `${props.group.entries.length} copies on disk` : 'On disk'}
            </h3>

            <Show when={yearSpread().length > 1}>
              <p class="inline-note warn">
                These copies are labelled with different years ({yearSpread().join(', ')}) — they
                may be different {noun()}s. Reassign one to split it onto its own card.
              </p>
            </Show>

            <ul class="paths">
              <For each={props.group.entries}>
                {(entry) => (
                  <li classList={{ 'copy-active': fixing() === entry.dir_name }}>
                    <code>{entry.path}</code>
                    <span class="path-meta">
                      matched as {entry.source} · confidence {entry.match_confidence.toFixed(2)}
                      <Show when={entry.low_confidence}> · low confidence</Show>
                      <Show when={entry.status !== 'matched'}> · {entry.status}</Show>
                    </span>
                    <div class="copy-actions">
                      <button
                        type="button"
                        class="ghost"
                        disabled={opening() === entry.dir_name}
                        onClick={() => showOnDisk(entry)}
                      >
                        {/* A loose video file is selected inside its folder rather
                            than played — this app never opens the film itself. */}
                        📂 {entry.is_file ? 'Show in folder' : 'Open folder'}
                      </button>
                      <Show when={entryNeedsAttention(entry) && entry.tmdb}>
                        <button
                          type="button"
                          disabled={confirming()}
                          onClick={() => acceptOne(entry)}
                        >
                          ✓ Correct
                        </button>
                      </Show>
                      <button
                        type="button"
                        class="ghost"
                        onClick={() =>
                          setFixing((open) => (open === entry.dir_name ? null : entry.dir_name))
                        }
                      >
                        {fixing() === entry.dir_name ? 'Cancel' : 'Reassign…'}
                      </button>
                    </div>
                  </li>
                )}
              </For>
            </ul>

            {/* One panel outside the <For>: that list is keyed by entry reference, so a
                form nested in a row would be thrown away and rebuilt — losing the typed
                query and its results — every time any copy is updated. */}
            <Show when={props.group.entries.find((entry) => entry.dir_name === fixing())}>
              {(entry) => (
                <FixMatch entry={entry()} kind={props.kind} onApplied={applied} />
              )}
            </Show>
          </section>
        </div>
      </div>
    </div>
  )
}
