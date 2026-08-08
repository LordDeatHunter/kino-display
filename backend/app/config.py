"""Application settings, loaded from the project-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_read_access_token: str = ""
    api_key: str = ""

    movies_dir: Path = Path("../Movies")
    data_dir: Path = Path("data")

    host: str = "127.0.0.1"
    port: int = 8000

    tmdb_language: str = "en-US"
    max_concurrency: int = 8

    @field_validator("movies_dir", "data_dir", mode="after")
    @classmethod
    def _resolve(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache.json"

    @property
    def overrides_path(self) -> Path:
        return self.data_dir / "overrides.json"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def frontend_dist(self) -> Path:
        return PROJECT_ROOT / "frontend" / "dist"

    def require_credentials(self) -> None:
        if not self.api_read_access_token and not self.api_key:
            raise RuntimeError(
                "No TMDB credentials found. Copy .env.example to .env and set "
                "API_READ_ACCESS_TOKEN (or API_KEY)."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
