import type { CacheEntry, MovieGroup } from './types'

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

/** Collapse folders that resolved to the same film into a single card. */
export function groupEntries(entries: CacheEntry[]): MovieGroup[] {
  const groups = new Map<string, MovieGroup>()

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

export function searchMatches(group: MovieGroup, query: string): boolean {
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

export type SortMode = 'title' | 'year' | 'rating' | 'runtime' | 'added'

export function sortGroups(groups: MovieGroup[], mode: SortMode): MovieGroup[] {
  const sorted = [...groups]
  switch (mode) {
    case 'year':
      return sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0) || sortKey(a.title).localeCompare(sortKey(b.title)))
    case 'rating':
      return sorted.sort((a, b) => b.rating - a.rating || sortKey(a.title).localeCompare(sortKey(b.title)))
    case 'runtime':
      return sorted.sort((a, b) => (b.runtime ?? 0) - (a.runtime ?? 0))
    case 'added':
      return sorted.sort((a, b) => b.latestFetch.localeCompare(a.latestFetch))
    default:
      return sorted.sort((a, b) => sortKey(a.title).localeCompare(sortKey(b.title)))
  }
}
