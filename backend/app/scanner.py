"""Scan the movie library and turn messy release folder names into (title, year)."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

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


def parse_name(raw_name: str) -> tuple[str, int | None]:
    """Turn a release folder name into a best-guess (title, year)."""
    name = BRACKET_RE.sub(" ", raw_name)

    # Scene-style names use dots as separators. Only collapse them when the name
    # has no spaces at all, so "Mr. Mom (1983)" keeps its period.
    if " " not in name.strip() and name.count(".") >= 2:
        name = name.replace(".", " ")
    name = name.replace("_", " ")

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


def scan_library(movies_dir: Path) -> list[ScannedEntry]:
    """List directories and loose video files one level below `movies_dir`."""
    if not movies_dir.exists():
        raise FileNotFoundError(f"Movie library not found: {movies_dir}")

    entries: list[ScannedEntry] = []
    for child in sorted(movies_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            key, is_file = child.name, False
        elif child.is_file() and child.suffix.lower() in VIDEO_EXTS:
            key, is_file = child.name, True
        else:
            continue

        source = Path(child.name).stem if is_file else child.name
        title, year = parse_name(source)
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
