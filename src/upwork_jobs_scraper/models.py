"""Data classes returned by the scraper."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any

# Fields that describe where a record came from; never overwritten by job details.
_PROVENANCE = frozenset({"source", "query"})


@dataclass
class Job:
    """One Upwork job posting.

    Listing fields come from search results and skill feeds. The ``client_*``,
    activity and requirement fields are only filled in from the job's own page
    (``details_fetched`` is then ``True``).
    """

    job_id: str
    title: str
    url: str
    uid: str | None = None
    source: str | None = None
    query: str | None = None
    description: str | None = None
    job_type: str | None = None
    fixed_budget: float | None = None
    hourly_min: float | None = None
    hourly_max: float | None = None
    currency: str | None = None
    experience_level: str | None = None
    duration: str | None = None
    duration_weeks: int | None = None
    workload: str | None = None
    skills: list[str] = field(default_factory=list)
    category: str | None = None
    category_group: str | None = None
    occupation: str | None = None
    posted_at: str | None = None
    renewed_at: str | None = None
    positions: int | None = None
    contract_to_hire: bool | None = None
    proposals: int | None = None
    interviewing: int | None = None
    invites_sent: int | None = None
    unanswered_invites: int | None = None
    hired: int | None = None
    client_last_active_at: str | None = None
    preferred_countries: list[str] = field(default_factory=list)
    min_job_success_score: int | None = None
    client_country: str | None = None
    client_city: str | None = None
    client_timezone: str | None = None
    client_payment_verified: bool | None = None
    client_rating: float | None = None
    client_reviews: int | None = None
    client_total_spent: float | None = None
    client_hires: int | None = None
    client_active_hires: int | None = None
    client_member_since: str | None = None
    client_industry: str | None = None
    client_enterprise: bool | None = None
    details_fetched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def merged(self, details: Job) -> Job:
        """A copy of this listing with every value the job page provides filled in."""
        updates: dict[str, Any] = {}
        for f in fields(self):
            if f.name in _PROVENANCE:
                continue
            value = getattr(details, f.name)
            if value is None or value == []:
                continue
            updates[f.name] = list(value) if isinstance(value, list) else value
        return replace(self, **updates)


@dataclass
class SearchPage:
    """One page of Upwork job search results."""

    url: str
    query: str
    page: int
    per_page: int
    total: int | None
    jobs: list[Job] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RelatedSkill:
    """A related skill linked from a skill's job feed, with its open-job count."""

    slug: str
    name: str
    url: str
    open_jobs: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillPage:
    """A skill's public job feed (``/freelance-jobs/<skill>/``)."""

    slug: str
    name: str | None
    url: str
    total_jobs: int | None
    jobs: list[Job] = field(default_factory=list)
    related_skills: list[RelatedSkill] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
