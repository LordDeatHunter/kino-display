"""Pydantic models describing the on-disk cache and the API payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class TmdbMovie(BaseModel):
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
    tmdb: TmdbMovie | None = None


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
