import type {
  CacheEntry,
  CacheFile,
  LibraryStats,
  MediaKind,
  SearchResult,
  SyncStatus,
} from './types'

/** FastAPI puts the human-readable half of an error in a JSON `detail`; unwrap it so
 *  messages shown in the UI read as sentences rather than as a serialised body. */
function errorMessage(status: number, statusText: string, body: string): string {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail) return detail
  } catch {
    // not JSON — fall through to the raw body
  }
  return `${status} ${statusText} ${body.slice(0, 200)}`.trim()
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(errorMessage(response.status, response.statusText, body))
  }
  return (await response.json()) as T
}

/** Every route is scoped to one library; the two never share a cache. */
export const fetchLibrary = (kind: MediaKind) => request<CacheFile>(`/api/library?kind=${kind}`)

export const fetchStats = (kind: MediaKind) => request<LibraryStats>(`/api/stats?kind=${kind}`)

export const fetchSyncStatus = (kind: MediaKind) =>
  request<SyncStatus>(`/api/sync/status?kind=${kind}`)

export const startSync = (
  kind: MediaKind,
  opts: { force?: boolean; retryUnmatched?: boolean } = {},
) => {
  const params = new URLSearchParams({
    kind,
    force: String(opts.force ?? false),
    retry_unmatched: String(opts.retryUnmatched ?? false),
  })
  return request<SyncStatus>(`/api/sync?${params}`, { method: 'POST' })
}

export const searchTmdb = (query: string, kind: MediaKind) =>
  request<{ image_base_url: string; results: SearchResult[] }>(
    `/api/tmdb/search?kind=${kind}&q=${encodeURIComponent(query)}`,
  )

export const setOverride = (dirName: string, tmdbId: number | null, kind: MediaKind) =>
  request<CacheEntry>('/api/overrides', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dir_name: dirName, tmdb_id: tmdbId, kind }),
  })

/** Accept the matches these folders already have, clearing their "check" flag. */
export const confirmMatches = (dirNames: string[], kind: MediaKind) =>
  request<CacheEntry[]>('/api/confirm', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dir_names: dirNames, kind }),
  })

/** Show this folder in the file manager of the machine running the server — which,
 *  for a localhost-only app, is the one you are sitting at. The browser cannot do it:
 *  a file:// link from an http:// page is blocked outright. */
export const openFolder = (dirName: string, kind: MediaKind) =>
  request<{ path: string }>('/api/open', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ dir_name: dirName, kind }),
  })

export const clearOverride = (dirName: string, kind: MediaKind) =>
  request<CacheEntry>(`/api/overrides/${encodeURIComponent(dirName)}?kind=${kind}`, {
    method: 'DELETE',
  })
