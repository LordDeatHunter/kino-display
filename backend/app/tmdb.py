"""Async TMDB API client plus the search-result matching heuristic."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import httpx

from .config import MediaKind, Settings
from .models import DEFAULT_IMAGE_BASE, CastMember, Episode, Season, TmdbTitle

API_BASE = "https://api.themoviedb.org/3"
MAX_ATTEMPTS = 4
CAST_LIMIT = 10

# Below this, the winning candidate is weak enough to be worth a second query.
RETRY_SCORE = 0.55

LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
ROMAN_ONE_RE = re.compile(r"\s+(?:i|1)$", re.IGNORECASE)


def deleet(title: str) -> str:
    """"VaCaTi0n" -> "VaCaTion". Only touches words that mix letters and digits,
    so "127 Hours" and "Blade Runner 2049" are left alone."""
    words = [
        word.translate(LEET_MAP)
        if any(ch.isdigit() for ch in word) and any(ch.isalpha() for ch in word)
        else word
        for word in title.split()
    ]
    return " ".join(words)


class TmdbError(RuntimeError):
    pass


def _typical_runtime(seasons: list[Season]) -> int | None:
    """The median episode length.

    TMDB leaves `episode_run_time` empty on most shows now, so without this a
    series would simply have no runtime to show or sort by. Specials are left out
    — a feature-length finale should not drag the number around.
    """
    lengths = sorted(
        episode.runtime
        for season in seasons
        if season.season_number != 0
        for episode in season.episodes
        if episode.runtime
    )
    return lengths[len(lengths) // 2] if lengths else None


def _aggregate_character(member: dict[str, Any]) -> str:
    """A show-wide cast entry lists its roles instead of one `character` field."""
    roles = member.get("roles") or []
    if roles:
        return str(roles[0].get("character") or "")
    return str(member.get("character") or "")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_candidate(parsed_title: str, parsed_year: int | None, candidate: dict[str, Any]) -> float:
    """Rate a search result 0..1 on how well it matches the parsed folder name."""
    target = _normalize(parsed_title)
    names = [candidate.get("title") or "", candidate.get("original_title") or ""]
    ratio = max(SequenceMatcher(None, target, _normalize(n)).ratio() for n in names if n) if any(names) else 0.0

    release = str(candidate.get("release_date") or "")
    cand_year = int(release[:4]) if release[:4].isdigit() else None
    if parsed_year and cand_year:
        delta = abs(parsed_year - cand_year)
        ratio += 0.15 if delta == 0 else (0.03 if delta == 1 else -0.25)
    elif parsed_year and not cand_year:
        ratio -= 0.1

    # Nudge popular titles ahead when scores are otherwise tied.
    ratio += min(float(candidate.get("popularity") or 0.0), 100.0) / 5000.0
    return max(0.0, min(1.0, ratio))


def pick_best(parsed_title: str, parsed_year: int | None, results: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in results:
        score = score_candidate(parsed_title, parsed_year, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score


def normalize_result(candidate: dict[str, Any]) -> dict[str, Any]:
    """Give a TV search result the field names a film result uses.

    Done at the edge so scoring, matching and the /api/tmdb/search payload never
    have to know which endpoint the candidate came from.
    """
    if "title" in candidate and "name" not in candidate:
        return candidate
    merged = dict(candidate)
    merged.setdefault("title", candidate.get("name") or "")
    merged.setdefault("original_title", candidate.get("original_name") or "")
    merged.setdefault("release_date", candidate.get("first_air_date") or "")
    return merged


class TmdbClient:
    def __init__(self, settings: Settings, kind: MediaKind = "movies") -> None:
        settings.require_credentials()
        self._settings = settings
        self.kind = kind
        # "movie" and "tv" are the TMDB path segments for both search and details.
        self._segment = "tv" if kind == "series" else "movie"
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrency))
        headers = {"accept": "application/json"}
        if settings.api_read_access_token:
            headers["Authorization"] = f"Bearer {settings.api_read_access_token}"
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers=headers,
            timeout=httpx.Timeout(20.0),
        )
        self._image_base: str | None = None

    async def __aenter__(self) -> "TmdbClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        if not self._settings.api_read_access_token and self._settings.api_key:
            query["api_key"] = self._settings.api_key

        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            async with self._semaphore:
                try:
                    response = await self._client.get(path, params=query)
                except httpx.HTTPError as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    response = None

            if response is None:
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429:
                await asyncio.sleep(float(response.headers.get("retry-after", 1)) + 0.5)
                continue
            if response.status_code == 404:
                raise TmdbError(f"404 for {path}")
            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise TmdbError(f"HTTP {response.status_code} for {path}: {response.text[:200]}")
            return response.json()

        raise TmdbError(f"Giving up on {path} after {MAX_ATTEMPTS} attempts ({last_error})")

    async def image_base_url(self) -> str:
        if self._image_base is None:
            try:
                config = await self._get("/configuration")
                self._image_base = config.get("images", {}).get("secure_base_url") or DEFAULT_IMAGE_BASE
            except TmdbError:
                self._image_base = DEFAULT_IMAGE_BASE
        return self._image_base

    async def search(self, title: str, year: int | None = None) -> list[dict[str, Any]]:
        path = f"/search/{self._segment}"
        params: dict[str, Any] = {
            "query": title,
            "include_adult": "true",
            "language": self._settings.tmdb_language,
        }
        if year:
            # /search/tv has no "year"; the equivalent filter is the first air year.
            params["first_air_date_year" if self._segment == "tv" else "year"] = year
        payload = await self._get(path, params)
        results = payload.get("results") or []
        if not results and year:
            # The folder's year is often the rip's year, not the release's.
            params.pop("first_air_date_year" if self._segment == "tv" else "year")
            payload = await self._get(path, params)
            results = payload.get("results") or []
        return [normalize_result(item) for item in results]

    async def find_best(
        self, title: str, year: int | None
    ) -> tuple[dict[str, Any] | None, float]:
        """Search TMDB for a parsed folder title, widening the query while the
        best candidate stays weak. Returns the winner and its score."""
        best, score = pick_best(title, year, await self.search(title, year))

        if score < RETRY_SCORE and year:
            # A year filter can hide the right film entirely — "Bad Trip (2020)"
            # is a 2021 TMDB release, and the filtered search returns junk.
            alt, alt_score = pick_best(title, year, await self.search(title, None))
            if alt_score > score:
                best, score = alt, alt_score

        for variant in (deleet(title), ROMAN_ONE_RE.sub("", title)):
            if score >= RETRY_SCORE or variant == title or not variant:
                continue
            # Score against the corrected query — the folder name is the typo.
            alt, alt_score = pick_best(variant, year, await self.search(variant, year))
            if alt_score > score:
                best, score = alt, alt_score

        return best, score

    async def details(self, tmdb_id: int) -> TmdbTitle:
        if self._segment == "tv":
            return await self._show_details(tmdb_id)
        return await self._movie_details(tmdb_id)

    async def _movie_details(self, movie_id: int) -> TmdbTitle:
        payload = await self._get(
            f"/movie/{movie_id}",
            {"language": self._settings.tmdb_language, "append_to_response": "credits"},
        )
        credits = payload.get("credits") or {}
        directors = [
            member.get("name", "")
            for member in credits.get("crew") or []
            if member.get("job") == "Director"
        ]
        cast = [
            CastMember(
                name=member.get("name") or "",
                character=member.get("character") or "",
                profile_path=member.get("profile_path"),
            )
            for member in (credits.get("cast") or [])[:CAST_LIMIT]
        ]
        return TmdbTitle(
            id=payload["id"],
            title=payload.get("title") or payload.get("original_title") or "",
            original_title=payload.get("original_title") or "",
            overview=payload.get("overview") or "",
            tagline=payload.get("tagline") or "",
            release_date=payload.get("release_date") or "",
            runtime=payload.get("runtime"),
            genres=[genre["name"] for genre in payload.get("genres") or []],
            vote_average=float(payload.get("vote_average") or 0.0),
            vote_count=int(payload.get("vote_count") or 0),
            popularity=float(payload.get("popularity") or 0.0),
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
            imdb_id=payload.get("imdb_id"),
            homepage=payload.get("homepage") or "",
            spoken_languages=[lang.get("english_name", "") for lang in payload.get("spoken_languages") or []],
            directors=directors,
            cast=cast,
            media_type="movie",
        )

    async def _show_details(self, tv_id: int) -> TmdbTitle:
        """A show plus every one of its seasons, episode lists included.

        That is one request per season on top of the show itself, which is why a
        series sync is markedly slower than a film one. They run concurrently under
        the shared semaphore, so the request rate is the same as everywhere else.
        """
        payload = await self._get(
            f"/tv/{tv_id}",
            {
                "language": self._settings.tmdb_language,
                # TV credits are per-episode; aggregate_credits is the show-wide roll-up.
                # external_ids is where a show's imdb_id lives.
                "append_to_response": "aggregate_credits,external_ids",
            },
        )
        credits = payload.get("aggregate_credits") or payload.get("credits") or {}
        cast = [
            CastMember(
                name=member.get("name") or "",
                character=_aggregate_character(member),
                profile_path=member.get("profile_path"),
            )
            for member in (credits.get("cast") or [])[:CAST_LIMIT]
        ]
        declared = [int(value) for value in payload.get("episode_run_time") or [] if value]

        # Specials (season 0) are real but belong after the numbered run.
        numbers = sorted(
            {
                int(season.get("season_number"))
                for season in payload.get("seasons") or []
                if season.get("season_number") is not None
            },
            key=lambda number: (number == 0, number),
        )
        fetched = await asyncio.gather(
            *(self.season_details(tv_id, number) for number in numbers), return_exceptions=True
        )
        # A season that failed to fetch is dropped rather than failing the show: a full
        # episode list is a bonus, the show itself is the point.
        seasons = [season for season in fetched if isinstance(season, Season)]

        return TmdbTitle(
            id=payload["id"],
            title=payload.get("name") or payload.get("original_name") or "",
            original_title=payload.get("original_name") or "",
            overview=payload.get("overview") or "",
            tagline=payload.get("tagline") or "",
            release_date=payload.get("first_air_date") or "",
            runtime=declared[0] if declared else _typical_runtime(seasons),
            genres=[genre["name"] for genre in payload.get("genres") or []],
            vote_average=float(payload.get("vote_average") or 0.0),
            vote_count=int(payload.get("vote_count") or 0),
            popularity=float(payload.get("popularity") or 0.0),
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
            imdb_id=(payload.get("external_ids") or {}).get("imdb_id"),
            homepage=payload.get("homepage") or "",
            spoken_languages=[lang.get("english_name", "") for lang in payload.get("spoken_languages") or []],
            directors=[creator.get("name", "") for creator in payload.get("created_by") or []],
            cast=cast,
            media_type="tv",
            number_of_seasons=payload.get("number_of_seasons"),
            number_of_episodes=payload.get("number_of_episodes"),
            networks=[network.get("name", "") for network in payload.get("networks") or []],
            seasons=seasons,
        )

    async def season_details(self, tv_id: int, season_number: int) -> Season:
        payload = await self._get(
            f"/tv/{tv_id}/season/{season_number}",
            {"language": self._settings.tmdb_language},
        )
        episodes = [
            Episode(
                episode_number=int(item.get("episode_number") or 0),
                name=item.get("name") or "",
                overview=item.get("overview") or "",
                air_date=item.get("air_date") or "",
                runtime=item.get("runtime"),
                still_path=item.get("still_path"),
                vote_average=float(item.get("vote_average") or 0.0),
            )
            for item in payload.get("episodes") or []
        ]
        return Season(
            season_number=season_number,
            name=payload.get("name") or f"Season {season_number}",
            overview=payload.get("overview") or "",
            air_date=payload.get("air_date") or "",
            episode_count=len(episodes),
            poster_path=payload.get("poster_path"),
            episodes=episodes,
        )
