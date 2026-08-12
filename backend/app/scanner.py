"""Scan the movie library and turn messy release folder names into (title, year)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from pathlib import Path

from .config import KIND_LABELS, MediaKind
from .models import ScannedEntry

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".m4v", ".mov", ".wmv", ".flv", ".webm",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".divx",
}

# [1080p], {YTS.MX}, [H264-mp4] ...
BRACKET_RE = re.compile(r"[\[\{][^\]\}]*[\]\}]")
# (2018) and the sloppy "( 2011 )" variant
PAREN_YEAR_RE = re.compile(r"\(\s*((?:19|20)\d{2})\s*\)")
BARE_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

# Tokens that are unambiguously release metadata, never part of a real title.
# Deliberately conservative: words like "cut", "complete" or "audio" are left
# alone because they do show up in genuine titles.
JUNK_RE = re.compile(
    r"""^(?:
        \d{3,4}p | 4k | 8k | uhd | hdrip | hdtv | bluray | blu-ray | brrip | bdrip |
        dvdrip | dvdscr | webrip | web-dl | webdl | web | amzn | nf | dsnp | hmax | itunes |
        hdr | hdr10 | hdr10\+ | dv | dolbyvision | imax | remux | repack | proper |
        unrated | uncut | extended | rerip | internal |
        x264 | x265 | h264 | h265 | hevc | avc | xvid | 10bit | 8bit |
        aac | aac2 | ac3 | eac3 | dts | dd | dd2 | dd5 | ddp | ddp5 | ddp2 | atmos | truehd |
        \d\.\d |
        yify | yts | rarbg | galaxyrg | galaxytv | tgx | nogrp | evo | fgt | sparks | cmrg |
        \d+(?:mb|gb) |
        eng | subs | subtitles
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# Junk that carries a group suffix, e.g. "x264-GalaxyRG" or "YTS.MX"
JUNK_PREFIX_RE = re.compile(
    r"^(?:x264|x265|h264|h265|hevc|avc|xvid|yts|yify|rarbg|atmos|ddp5|dd5)[.\-]\S*$",
    re.IGNORECASE,
)

# Spoken-language markers used by YTS-style releases
LANGUAGE_RE = re.compile(
    r"^(?:korean|japanese|chinese|cantonese|mandarin|french|spanish|german|italian|"
    r"hindi|tamil|telugu|russian|turkish|thai|polish|dutch|swedish|norwegian|danish|"
    r"portuguese|arabic|hebrew|persian|indonesian|vietnamese)$",
    re.IGNORECASE,
)

# Season and pack markers, stripped from series names only: "S01", "S01-S09",
# "S01E02", "Season 1", "Seasons 1-3", "Complete". Applied to the whole string
# rather than per token because "Season 1" would otherwise leave a bare "1" behind.
# A bare "Series" is left alone — "A Series of Unfortunate Events" is a real show.
SEASON_RE = re.compile(
    r"""\s*\b(?:
        s\d{1,2}\s*-\s*s?\d{1,2} |
        s\d{1,2}e\d{1,3} |
        s\d{1,2} |
        seasons?\s*\d{1,2}\s*-\s*\d{1,2} |
        seasons?\s*\d{1,2} |
        complete(?:\s+series)?
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)

MAX_PLAUSIBLE_YEAR = dt.date.today().year + 2


def _strip_junk_tokens(text: str) -> str:
    kept: list[str] = []
    for token in text.split():
        bare = token.strip(" .,-_")
        if not bare:
            continue
        if JUNK_RE.match(bare) or JUNK_PREFIX_RE.match(bare) or LANGUAGE_RE.match(bare):
            continue
        kept.append(token)
    return " ".join(kept)


def _tidy(text: str) -> str:
    text = text.replace("_", " ")
    # " - " is a separator in this library ("Pirates of the Caribbean - At Worlds End"),
    # but a bare hyphen belongs to the title ("Spider-Man", "K-PAX").
    text = re.sub(r"\s+-\s+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,-_&")


def parse_name(raw_name: str, kind: MediaKind = "movies") -> tuple[str, int | None]:
    """Turn a release folder name into a best-guess (title, year)."""
    name = BRACKET_RE.sub(" ", raw_name)

    # Scene-style names use dots as separators. Only collapse them when the name
    # has no spaces at all, so "Mr. Mom (1983)" keeps its period.
    if " " not in name.strip() and name.count(".") >= 2:
        name = name.replace(".", " ")
    name = name.replace("_", " ")

    if kind == "series":
        name = SEASON_RE.sub(" ", name)

    year: int | None = None
    paren_years = list(PAREN_YEAR_RE.finditer(name))
    if paren_years:
        last = paren_years[-1]
        year = int(last.group(1))
        title_part = name[: last.start()]
    else:
        title_part = name
        for match in reversed(list(BARE_YEAR_RE.finditer(name))):
            candidate = int(match.group(1))
            # Skip a leading year — "2001 A Space Odyssey" is a title, not a date —
            # and skip implausible futures so "Blade Runner 2049" survives.
            if match.start() == 0 or candidate > MAX_PLAUSIBLE_YEAR:
                continue
            year = candidate
            title_part = name[: match.start()]
            break

    title = _tidy(_strip_junk_tokens(title_part))
    if not title:
        # Everything got stripped (e.g. the folder is just "[1080p]"); fall back
        # to the raw name so the entry is still searchable.
        title = _tidy(_strip_junk_tokens(BRACKET_RE.sub(" ", raw_name))) or raw_name.strip()
    return title, year


def scan_library(root: Path, kind: MediaKind = "movies") -> list[ScannedEntry]:
    """List directories and loose video files one level below `root`.

    For series that one level is the show folder — seasons and episodes live
    below it and come from TMDB, not from disk.
    """
    if not root.exists():
        raise FileNotFoundError(f"{KIND_LABELS[kind].capitalize()} library not found: {root}")

    entries: list[ScannedEntry] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            key, is_file = child.name, False
        elif child.is_file() and child.suffix.lower() in VIDEO_EXTS:
            key, is_file = child.name, True
        else:
            continue

        source = Path(child.name).stem if is_file else child.name
        title, year = parse_name(source, kind)
        entries.append(
            ScannedEntry(
                dir_name=key,
                path=str(child),
                is_file=is_file,
                parsed_title=title,
                parsed_year=year,
            )
        )
    return entries


def scan_libraries(
    roots: Sequence[Path], kind: MediaKind = "movies"
) -> tuple[list[ScannedEntry], list[str]]:
    """Scan every configured library root and merge the results.

    Returns the merged entries plus a note for everything that was skipped:

    - a root that is not there right now — an unplugged drive is worth mentioning but
      is not a reason to refuse to scan the roots that are;
    - a folder name an earlier root already used, since the cache is keyed by folder
      name alone and can only hold one of them.

    Every root missing at once is still an error: that is a broken config, not a
    library that happens to be empty.
    """
    label = KIND_LABELS[kind]
    if not roots:
        raise FileNotFoundError(f"No {label} library configured")

    present = [path for path in roots if path.exists()]
    if not present:
        raise FileNotFoundError(
            f"{label.capitalize()} library not found: " + ", ".join(str(path) for path in roots)
        )

    notes = [f"not there right now, skipped: {path}" for path in roots if path not in present]
    entries: list[ScannedEntry] = []
    seen: set[str] = set()
    for root in present:
        for entry in scan_library(root, kind):
            if entry.dir_name in seen:
                notes.append(f"folder name already seen, skipped: {entry.path}")
                continue
            seen.add(entry.dir_name)
            entries.append(entry)

    entries.sort(key=lambda entry: entry.dir_name.lower())
    return entries, notes
