export type EntryStatus = 'matched' | 'unmatched' | 'ignored' | 'error'

/** The two libraries the app keeps side by side, one per tab. */
export type MediaKind = 'movies' | 'series'

export interface CastMember {
  name: string
  character: string
  profile_path: string | null
}

export interface Episode {
  episode_number: number
  name: string
  overview: string
  air_date: string
  runtime: number | null
  still_path: string | null
  vote_average: number
}

export interface Season {
  season_number: number
  name: string
  overview: string
  air_date: string
  episode_count: number
  poster_path: string | null
  episodes: Episode[]
}

/** One film or one show — shows reuse the film field names (see models.py). */
export interface TmdbTitle {
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
  media_type: 'movie' | 'tv'
  number_of_seasons: number | null
  number_of_episodes: number | null
  networks: string[]
  seasons: Season[]
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
  tmdb: TmdbTitle | null
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
  kind: MediaKind
  running: boolean
  total: number
  done: number
  current: string
  started_at: string
  finished_at: string
  report: SyncReport | null
  error: string | null
}

export interface LibraryStats {
  kind: MediaKind
  total: number
  by_status: Record<string, number>
  low_confidence: number
  synced_at: string
  /** The folders configured for this library — empty means "never set up". */
  dirs: string[]
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

/** One card in the grid: several folders can be the same title (different rips). */
export interface TitleGroup {
  key: string
  entries: CacheEntry[]
  tmdb: TmdbTitle | null
  title: string
  year: number | null
  rating: number
  runtime: number | null
  genres: string[]
  needsAttention: boolean
  latestFetch: string
}
