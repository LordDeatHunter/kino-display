import type { CacheEntry, CacheFile, SearchResult, SyncStatus } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`${response.status} ${response.statusText} ${detail.slice(0, 200)}`)
  }
  return (await response.json()) as T
}

export const fetchMovies = () => request<CacheFile>('/api/movies')

export const fetchSyncStatus = () => request<SyncStatus>('/api/sync/status')

export const startSync = (opts: { force?: boolean; retryUnmatched?: boolean } = {}) => {
  const params = new URLSearchParams({
    force: String(opts.force ?? false),
    retry_unmatched: String(opts.retryUnmatched ?? false),
  })
  return request<SyncStatus>(`/api/sync?${params}`, { method: 'POST' })
}

export const searchTmdb = (query: string) =>
  request<{ image_base_url: string; results: SearchResult[] }>(
    `/api/tmdb/search?q=${encodeURIComponent(query)}`,
  )

export const setOverride = (dirName: string, tmdbId: number | null) =>
  request<CacheEntry>('/api/overrides', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dir_name: dirName, tmdb_id: tmdbId }),
  })

/** Accept the matches these folders already have, clearing their "check" flag. */
export const confirmMatches = (dirNames: string[]) =>
  request<CacheEntry[]>('/api/confirm', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dir_names: dirNames }),
  })

export const clearOverride = (dirName: string) =>
  request<CacheEntry>(`/api/overrides/${encodeURIComponent(dirName)}`, { method: 'DELETE' })
