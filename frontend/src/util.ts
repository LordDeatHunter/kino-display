import type { CacheEntry, TitleGroup } from './types'

/** Artwork is served by our own backend, which caches it on disk — the browser
 *  never contacts image.tmdb.org, so a DNS blip can't blank the grid. */
export const imageUrl = (path: string | null | undefined, size: string) =>
  path ? `/api/img/${size}${path.startsWith('/') ? path : `/${path}`}` : null

export function formatRuntime(minutes: number | null): string {
  if (!minutes) return ''
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return hours ? `${hours}h ${rest}m` : `${rest}m`
}

export const yearOf = (entry: CacheEntry): number | null => {
  const released = entry.tmdb?.release_date?.slice(0, 4)
  if (released && /^\d{4}$/.test(released)) return Number(released)
  return entry.parsed_year
}

export const entryNeedsAttention = (entry: CacheEntry) =>
  entry.status !== 'matched' || entry.low_confidence

/** Distinct years the folder names claim. More than one across copies of the "same"
 *  film usually means an original and a remake got merged onto one card.
 *
 *  Deliberately `parsed_year` and not `yearOf`: the latter prefers the TMDB release
 *  date, which is identical for every entry in a `tmdb:` group, so it always yields
 *  exactly one value and can never spot a disagreement. */
export const parsedYearSpread = (entries: CacheEntry[]): number[] => {
  const years = entries
    .map((entry) => entry.parsed_year)
    .filter((year): year is number => year !== null)
  return [...new Set(years)].sort((a, b) => a - b)
}

/** Flagged folders that do have a match — the ones "accept" applies to.
 *
 *  Groups whose copies disagree about the year are left out on purpose: accepting in
 *  bulk pins every copy to the same id and clears the only hint the merge was wrong.
 *  They stay fixable one copy at a time in the modal. */
export const confirmableEntries = (groups: TitleGroup[]): string[] =>
  groups
    .filter(
      (group) => group.needsAttention && group.tmdb && parsedYearSpread(group.entries).length < 2,
    )
    .flatMap((group) => group.entries.filter(entryNeedsAttention).map((entry) => entry.dir_name))

/** Collapse folders that resolved to the same film into a single card. */
export function groupEntries(entries: CacheEntry[]): TitleGroup[] {
  const groups = new Map<string, TitleGroup>()

  for (const entry of entries) {
    if (entry.status === 'ignored') continue
    const key = entry.tmdb ? `tmdb:${entry.tmdb.id}` : `dir:${entry.dir_name}`
    const existing = groups.get(key)
    if (existing) {
      existing.entries.push(entry)
      existing.needsAttention ||= entryNeedsAttention(entry)
      if (entry.fetched_at > existing.latestFetch) existing.latestFetch = entry.fetched_at
      continue
    }
    groups.set(key, {
      key,
      entries: [entry],
      tmdb: entry.tmdb,
      title: entry.tmdb?.title || entry.parsed_title || entry.dir_name,
      year: yearOf(entry),
      rating: entry.tmdb?.vote_average ?? 0,
      runtime: entry.tmdb?.runtime ?? null,
      genres: entry.tmdb?.genres ?? [],
      needsAttention: entryNeedsAttention(entry),
      latestFetch: entry.fetched_at,
    })
  }

  return [...groups.values()]
}

const sortKey = (title: string) => title.replace(/^(the|a|an)\s+/i, '').toLowerCase()

export function searchMatches(group: TitleGroup, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  const haystack = [
    group.title,
    group.tmdb?.original_title ?? '',
    group.tmdb?.tagline ?? '',
    ...(group.tmdb?.directors ?? []),
    ...(group.tmdb?.cast ?? []).map((member) => member.name),
    ...group.genres,
    ...group.entries.map((entry) => entry.dir_name),
  ]
    .join(' ')
    .toLowerCase()
  return needle.split(/\s+/).every((word) => haystack.includes(word))
}

export type SortMode =
  | 'title'
  | 'year'
  | 'rating'
  | 'votes'
  | 'runtime'
  | 'seasons'
  | 'popularity'
  | 'copies'
  | 'added'

export type SortDirection = 'asc' | 'desc'

/** How each field reads when you first pick it — titles A→Z, everything else best/newest first. */
export const DEFAULT_DIRECTION: Record<SortMode, SortDirection> = {
  title: 'asc',
  year: 'desc',
  rating: 'desc',
  votes: 'desc',
  runtime: 'desc',
  seasons: 'desc',
  popularity: 'desc',
  copies: 'desc',
  added: 'desc',
}

/** `null` means "no value" — those groups sink to the bottom in both directions. */
const SORT_VALUE: Record<SortMode, (group: TitleGroup) => number | string | null> = {
  title: (group) => sortKey(group.title),
  year: (group) => group.year,
  rating: (group) => group.rating || null,
  votes: (group) => group.tmdb?.vote_count || null,
  runtime: (group) => group.runtime,
  seasons: (group) => group.tmdb?.number_of_seasons ?? null,
  popularity: (group) => group.tmdb?.popularity || null,
  copies: (group) => group.entries.length,
  added: (group) => group.latestFetch || null,
}

const byTitle = (a: TitleGroup, b: TitleGroup) => sortKey(a.title).localeCompare(sortKey(b.title))

export function sortGroups(
  groups: TitleGroup[],
  mode: SortMode,
  direction: SortDirection = DEFAULT_DIRECTION[mode],
): TitleGroup[] {
  const value = SORT_VALUE[mode] ?? SORT_VALUE.title
  const flip = direction === 'desc' ? -1 : 1

  return [...groups].sort((a, b) => {
    const left = value(a)
    const right = value(b)

    if (left === null || right === null) {
      if (left === right) return byTitle(a, b)
      return left === null ? 1 : -1
    }

    const delta =
      typeof left === 'string' && typeof right === 'string'
        ? left.localeCompare(right)
        : Number(left) - Number(right)

    // Title stays the tie-break, always A→Z, so equal ratings read predictably.
    return delta === 0 ? byTitle(a, b) : delta * flip
  })
}
