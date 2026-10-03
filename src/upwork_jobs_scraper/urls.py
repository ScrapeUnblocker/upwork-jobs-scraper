"""Build and parse Upwork job search, skill feed and job page URLs."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from urllib.parse import parse_qsl, quote, urlsplit

BASE_URL = "https://www.upwork.com"
SEARCH_PATH = "/nx/search/jobs/"

# Sort orders a signed-out visitor can use. Sorting by client spend or rating
# needs an Upwork account.
SORTS: dict[str, str | None] = {"relevance": None, "newest": "recency"}

JOB_TYPES: dict[str, str] = {"hourly": "0", "fixed": "1"}

EXPERIENCE_LEVELS: dict[str, str] = {"entry": "1", "intermediate": "2", "expert": "3"}

# Project length -> Upwork's ``duration_v3`` value.
DURATIONS: dict[str, str] = {
    "week": "week",  # less than 1 month
    "month": "month",  # 1 to 3 months
    "semester": "semester",  # 3 to 6 months
    "ongoing": "ongoing",  # more than 6 months
}

CLIENT_HIRES: dict[str, str] = {"none": "0", "1-9": "1-9", "10+": "10-"}

PER_PAGE_OPTIONS = (10, 20, 50)

_CIPHERTEXT_RE = re.compile(r"~0[0-9a-zA-Z]{8,}")
_SKILL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SKILL_PATH_RE = re.compile(r"/freelance-jobs/([^/?#]+)")


def _check(kind: str, values: Iterable[str], allowed: dict[str, str]) -> tuple[str, ...]:
    out = tuple(dict.fromkeys(v.strip().lower() for v in values if v and v.strip()))
    bad = [v for v in out if v not in allowed]
    if bad:
        raise ValueError(f"unknown {kind} {bad[0]!r}; choose from {', '.join(allowed)}")
    return out


def _reverse(allowed: dict[str, str], raw: str) -> tuple[str, ...] | None:
    lookup = {v: k for k, v in allowed.items() if v is not None}
    names = [lookup.get(part) for part in raw.split(",") if part]
    return tuple(n for n in names if n) if names and all(names) else None


@dataclass(frozen=True)
class SearchQuery:
    """An Upwork job search, as a signed-out visitor can run it.

    Args:
        query: Keywords, e.g. ``"web scraping"``.
        sort: ``"relevance"`` (default) or ``"newest"``.
        job_type: ``"hourly"`` or ``"fixed"`` (default: both).
        experience: Any of ``"entry"``, ``"intermediate"``, ``"expert"``.
        duration: Any of ``"week"``, ``"month"``, ``"semester"``, ``"ongoing"``.
        client_hires: Any of ``"none"``, ``"1-9"``, ``"10+"`` (the client's past hires).
        per_page: 10, 20 or 50 results per page.
        page: 1-based page number.
        extra: Raw ``(key, value)`` URL parameters passed through unchanged.
    """

    query: str = ""
    sort: str = "relevance"
    job_type: str | None = None
    experience: tuple[str, ...] = ()
    duration: tuple[str, ...] = ()
    client_hires: tuple[str, ...] = ()
    per_page: int = 10
    page: int = 1
    extra: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.sort not in SORTS:
            raise ValueError(f"unknown sort {self.sort!r}; choose from {', '.join(SORTS)}")
        if self.job_type is not None and self.job_type not in JOB_TYPES:
            raise ValueError(f"unknown job type {self.job_type!r}; choose hourly or fixed")
        object.__setattr__(
            self, "experience", _check("experience level", self.experience, EXPERIENCE_LEVELS)
        )
        object.__setattr__(self, "duration", _check("duration", self.duration, DURATIONS))
        object.__setattr__(
            self, "client_hires", _check("client hires value", self.client_hires, CLIENT_HIRES)
        )
        if self.per_page not in PER_PAGE_OPTIONS:
            raise ValueError(f"per_page must be one of {PER_PAGE_OPTIONS}")
        if self.page < 1:
            raise ValueError("page must be at least 1")

    def params(self) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = []
        if self.query:
            params.append(("q", self.query))
        if SORTS[self.sort]:
            params.append(("sort", SORTS[self.sort] or ""))
        if self.job_type:
            params.append(("t", JOB_TYPES[self.job_type]))
        if self.experience:
            params.append(
                ("contractor_tier", ",".join(EXPERIENCE_LEVELS[e] for e in self.experience))
            )
        if self.duration:
            params.append(("duration_v3", ",".join(DURATIONS[d] for d in self.duration)))
        if self.client_hires:
            params.append(("client_hires", ",".join(CLIENT_HIRES[c] for c in self.client_hires)))
        if self.per_page != PER_PAGE_OPTIONS[0]:
            params.append(("per_page", str(self.per_page)))
        if self.page > 1:
            params.append(("page", str(self.page)))
        params.extend(self.extra)
        return params

    def to_url(self) -> str:
        query = "&".join(f"{k}={quote(v, safe=',-')}" for k, v in self.params())
        return f"{BASE_URL}{SEARCH_PATH}" + (f"?{query}" if query else "")

    def with_page(self, page: int) -> SearchQuery:
        return replace(self, page=page)

    @classmethod
    def from_url(cls, url: str) -> SearchQuery:
        """Rebuild a query from an Upwork job search URL copied from the browser."""
        parts = urlsplit(url)
        if parts.netloc and not parts.netloc.endswith("upwork.com"):
            raise ValueError(f"not an Upwork URL: {url}")
        if not parts.path.rstrip("/").endswith("/search/jobs"):
            raise ValueError(f"not an Upwork job search URL: {url}")
        options: dict[str, object] = {}
        extra: list[tuple[str, str]] = []
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            if key == "q":
                options["query"] = value
            elif key == "sort" and value in ("recency", "relevance+desc", "relevance desc"):
                options["sort"] = "newest" if value == "recency" else "relevance"
            elif key == "t" and value in ("0", "1"):
                options["job_type"] = "hourly" if value == "0" else "fixed"
            elif key == "contractor_tier" and _reverse(EXPERIENCE_LEVELS, value):
                options["experience"] = _reverse(EXPERIENCE_LEVELS, value)
            elif key == "duration_v3" and _reverse(DURATIONS, value):
                options["duration"] = _reverse(DURATIONS, value)
            elif key == "client_hires" and _reverse(CLIENT_HIRES, value):
                options["client_hires"] = _reverse(CLIENT_HIRES, value)
            elif key == "per_page" and value.isdigit() and int(value) in PER_PAGE_OPTIONS:
                options["per_page"] = int(value)
            elif key == "page" and value.isdigit() and int(value) >= 1:
                options["page"] = int(value)
            elif key == "nbs":  # a tracking flag the site adds; carries no filter
                continue
            else:
                extra.append((key, value))
        return cls(extra=tuple(extra), **options)  # type: ignore[arg-type]


def job_id_from(value: str) -> str:
    """Normalise a job reference to its ciphertext id (``~02...``).

    Accepts the id itself, a job URL (``/jobs/~02...`` or
    ``/freelance-jobs/apply/<title>_~02.../``) or the numeric job uid.
    """
    value = (value or "").strip()
    match = _CIPHERTEXT_RE.search(value)
    if match:
        return match.group(0)
    if value.isdigit() and len(value) >= 8:
        return f"~02{value}"
    raise ValueError(f"not an Upwork job id or URL: {value!r}")


def job_url(job: str) -> str:
    """Canonical job page URL for a job id, uid or URL."""
    return f"{BASE_URL}/jobs/{job_id_from(job)}"


def skill_slug(value: str) -> str:
    """Normalise a skill to its feed slug.

    Accepts a slug (``web-scraping``), a skill name (``Web Scraping``) or a
    feed URL (``https://www.upwork.com/freelance-jobs/web-scraping/``).
    """
    value = (value or "").strip()
    match = _SKILL_PATH_RE.search(value)
    if match:
        value = match.group(1)
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug or not _SKILL_SLUG_RE.match(slug) or slug == "apply":
        raise ValueError(f"not an Upwork skill: {value!r}")
    return slug


def skill_url(skill: str) -> str:
    """Public job feed URL for a skill slug, name or URL."""
    return f"{BASE_URL}/freelance-jobs/{skill_slug(skill)}/"
