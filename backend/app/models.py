"""Pydantic models describing the on-disk cache and the API payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import MediaKind

# Deliberately not bumped for the series work: every field added below is optional
# with a default, so an existing cache.json still validates and nothing is refetched.
SCHEMA_VERSION = 1
DEFAULT_IMAGE_BASE = "https://image.tmdb.org/t/p/"

EntryStatus = Literal["matched", "unmatched", "ignored", "error"]


class ScannedEntry(BaseModel):
    """A directory (or loose video file) found in the library, after name parsing."""

    dir_name: str
    path: str
    is_file: bool = False
    parsed_title: str
    parsed_year: int | None = None


class CastMember(BaseModel):
    name: str
    character: str = ""
    profile_path: str | None = None


class Episode(BaseModel):
    episode_number: int
    name: str = ""
    overview: str = ""
    air_date: str = ""
    runtime: int | None = None
    still_path: str | None = None
    vote_average: float = 0.0


class Season(BaseModel):
    season_number: int
    name: str = ""
    overview: str = ""
    air_date: str = ""
    episode_count: int = 0
    poster_path: str | None = None
    episodes: list[Episode] = Field(default_factory=list)


class TmdbTitle(BaseModel):
    """One film or one show.

    Shows are folded into the film shape rather than given their own model: `name`
    becomes `title`, `first_air_date` becomes `release_date`, creators become
    `directors`, so grouping, sorting and every UI component work on both unchanged.
    The TV-only extras hang off the end.
    """

    id: int
    title: str
    original_title: str = ""
    overview: str = ""
    tagline: str = ""
    release_date: str = ""
    runtime: int | None = None
    genres: list[str] = Field(default_factory=list)
    vote_average: float = 0.0
    vote_count: int = 0
    popularity: float = 0.0
    poster_path: str | None = None
    backdrop_path: str | None = None
    imdb_id: str | None = None
    homepage: str = ""
    spoken_languages: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    cast: list[CastMember] = Field(default_factory=list)

    media_type: Literal["movie", "tv"] = "movie"
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    networks: list[str] = Field(default_factory=list)
    seasons: list[Season] = Field(default_factory=list)

    @property
    def year(self) -> int | None:
        return int(self.release_date[:4]) if self.release_date[:4].isdigit() else None


class CacheEntry(BaseModel):
    dir_name: str
    path: str
    is_file: bool = False
    parsed_title: str = ""
    parsed_year: int | None = None
    status: EntryStatus = "unmatched"
    source: Literal["search", "override", "none"] = "none"
    match_confidence: float = 0.0
    low_confidence: bool = False
    fetched_at: str = ""
    error: str | None = None
    tmdb: TmdbTitle | None = None


class CacheFile(BaseModel):
    schema_version: int = SCHEMA_VERSION
    synced_at: str = ""
    image_base_url: str = DEFAULT_IMAGE_BASE
    entries: dict[str, CacheEntry] = Field(default_factory=dict)


class SyncReport(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    refetched: list[str] = Field(default_factory=list)
    unchanged: int = 0
    unmatched: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def fetched_count(self) -> int:
        return len(self.added) + len(self.refetched)


class SyncStatus(BaseModel):
    kind: MediaKind = "movies"
    running: bool = False
    total: int = 0
    done: int = 0
    current: str = ""
    started_at: str = ""
    finished_at: str = ""
    report: SyncReport | None = None
    error: str | None = None


class OverrideRequest(BaseModel):
    dir_name: str
    tmdb_id: int | None = None
    kind: MediaKind = "movies"


class ConfirmRequest(BaseModel):
    """Accept the match a folder already has, clearing its "check me" flag."""

    dir_names: list[str]
    kind: MediaKind = "movies"
