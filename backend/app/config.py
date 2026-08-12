"""Application settings, loaded from config.json and the project-root .env file."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    NoDecode,
    SettingsConfigDict,
)
from pydantic_settings.sources import DotEnvSettingsSource, PydanticBaseSettingsSource

# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Written by `python main.py`; see config.example.json.
CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULT_MOVIES_DIR = "../Movies"


class _TolerantJsonSource(JsonConfigSettingsSource):
    """Ignore a missing/corrupt config.json instead of failing every command."""

    def _read_file(self, file_path: Any) -> dict[str, Any]:
        try:
            data = super()._read_file(file_path)
        except (json.JSONDecodeError, OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        json_file=CONFIG_PATH,
        json_file_encoding="utf-8",
        extra="ignore",
    )

    api_read_access_token: str = ""
    api_key: str = ""

    # NoDecode: an env var here is a plain path (or several joined by os.pathsep),
    # not the JSON list pydantic-settings would otherwise expect for a list field.
    # The legacy singular "movies_dir" key/variable is still accepted.
    movies_dirs: Annotated[list[Path], NoDecode] = Field(
        default_factory=lambda: [Path(DEFAULT_MOVIES_DIR)],
        validation_alias=AliasChoices("movies_dirs", "movies_dir"),
    )
    data_dir: Path = Path("data")

    host: str = "127.0.0.1"
    port: int = 8000

    tmdb_language: str = "en-US"
    max_concurrency: int = 8

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """config.json beats .env, but a real environment variable still wins."""
        return (
            init_settings,
            env_settings,
            _TolerantJsonSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )

    @field_validator("movies_dirs", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        """Accept a list of paths, or one string holding os.pathsep-separated paths."""
        if isinstance(value, (str, Path)):
            value = str(value).split(os.pathsep)
        if not isinstance(value, (list, tuple)):
            return value
        return [item for item in (str(part).strip() for part in value) if item]

    @field_validator("data_dir", mode="after")
    @classmethod
    def _resolve(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("movies_dirs", mode="after")
    @classmethod
    def _resolve_each(cls, value: list[Path]) -> list[Path]:
        resolved: list[Path] = []
        for path in value:
            full = path if path.is_absolute() else (PROJECT_ROOT / path).resolve()
            if full not in resolved:
                resolved.append(full)
        return resolved

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


def env_movies_dirs() -> list[str] | None:
    """MOVIES_DIRS as supplied by the environment or .env — None if neither sets it.

    This is the default the first-run prompt falls back to; with no default, main.py
    insists on the folder picker. Several folders are joined by os.pathsep, and the
    old singular MOVIES_DIR still works.
    """
    raw = os.environ.get("MOVIES_DIRS") or os.environ.get("MOVIES_DIR")
    if raw is None:
        value = DotEnvSettingsSource(Settings)().get("movies_dirs")
        raw = value if isinstance(value, str) else None
    parts = [part.strip() for part in (raw or "").split(os.pathsep)]
    return [part for part in parts if part] or None
