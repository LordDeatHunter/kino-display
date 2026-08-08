export type EntryStatus = 'matched' | 'unmatched' | 'ignored' | 'error'

export interface CastMember {
  name: string
  character: string
  profile_path: string | null
}

export interface TmdbMovie {
  id: number
  title: string
  original_title: string
  overview: string
  tagline: string
  release_date: string
  runtime: number | null
  genres: string[]
  vote_average: number
  vote_count: number
  popularity: number
  poster_path: string | null
  backdrop_path: string | null
  imdb_id: string | null
  homepage: string
  spoken_languages: string[]
  directors: string[]
  cast: CastMember[]
}

export interface CacheEntry {
  dir_name: string
  path: string
  is_file: boolean
  parsed_title: string
  parsed_year: number | null
  status: EntryStatus
  source: 'search' | 'override' | 'none'
  match_confidence: number
  low_confidence: boolean
  fetched_at: string
  error: string | null
  tmdb: TmdbMovie | null
}

export interface CacheFile {
  schema_version: number
  synced_at: string
  image_base_url: string
  entries: Record<string, CacheEntry>
}

export interface SyncReport {
  added: string[]
  removed: string[]
  refetched: string[]
  unchanged: number
  unmatched: number
  errors: string[]
}

export interface SyncStatus {
  running: boolean
  total: number
  done: number
  current: string
  started_at: string
  finished_at: string
  report: SyncReport | null
  error: string | null
}

export interface SearchResult {
  id: number
  title: string
  original_title: string
  release_date: string | null
  overview: string
  poster_path: string | null
  vote_average: number
}

/** One card in the grid: several folders can be the same film (different rips). */
export interface MovieGroup {
  key: string
  entries: CacheEntry[]
  tmdb: TmdbMovie | null
  title: string
  year: number | null
  rating: number
  runtime: number | null
  genres: string[]
  needsAttention: boolean
  latestFetch: string
}
