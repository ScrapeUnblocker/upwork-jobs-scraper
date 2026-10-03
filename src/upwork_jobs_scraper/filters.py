"""Client-side job filters.

Upwork keeps several useful search filters (budget, hourly rate, proposals,
payment verified) behind its login. :class:`JobFilter` applies them locally
instead: listing-level checks run on search/feed results, and client-level
checks run after the job pages have been fetched.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .models import Job
from .parsing import normalize_country, parse_iso


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


@dataclass(frozen=True)
class JobFilter:
    """Conditions a job must meet to be kept.

    Listing-level (no extra requests):
        min_fixed_budget: Drop fixed-price jobs with a smaller budget.
        min_hourly_rate: Drop hourly jobs whose posted top rate is below this
            (hourly jobs without a posted rate are kept).
        posted_within_hours: Drop jobs posted (or renewed) longer ago than this.
        exclude_keywords: Drop jobs whose title or description mentions any of these.

    Client-level (need each job's page, one request per job):
        payment_verified: Keep only clients with a verified payment method.
        max_proposals: Keep only jobs with at most this many proposals so far.
        min_client_spent: Keep only clients who have spent at least this much (USD).
        min_client_rating: Keep only clients rated at least this (0-5).
        client_countries: Keep only clients located in one of these countries.
    """

    min_fixed_budget: float | None = None
    min_hourly_rate: float | None = None
    posted_within_hours: float | None = None
    exclude_keywords: tuple[str, ...] = ()
    payment_verified: bool = False
    max_proposals: int | None = None
    min_client_spent: float | None = None
    min_client_rating: float | None = None
    client_countries: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "exclude_keywords", tuple(k.strip() for k in self.exclude_keywords if k.strip())
        )
        countries = (normalize_country(c) for c in self.client_countries)
        object.__setattr__(self, "client_countries", tuple(c for c in countries if c))

    @property
    def needs_details(self) -> bool:
        """True when some condition can only be checked on the job's own page."""
        return bool(
            self.payment_verified
            or self.max_proposals is not None
            or self.min_client_spent is not None
            or self.min_client_rating is not None
            or self.client_countries
        )

    def listing_only(self) -> JobFilter:
        """A copy without the client-level conditions (checkable without job pages)."""
        return replace(
            self,
            payment_verified=False,
            max_proposals=None,
            min_client_spent=None,
            min_client_rating=None,
            client_countries=(),
        )

    def match_listing(self, job: Job, *, now: _dt.datetime | None = None) -> bool:
        if self.min_fixed_budget is not None and job.job_type == "fixed":
            if (job.fixed_budget or 0) < self.min_fixed_budget:
                return False
        if self.min_hourly_rate is not None and job.job_type == "hourly":
            top = job.hourly_max or job.hourly_min
            if top is not None and top < self.min_hourly_rate:
                return False
        if self.posted_within_hours is not None:
            stamps = [parse_iso(job.posted_at), parse_iso(job.renewed_at)]
            latest = max((s for s in stamps if s is not None), default=None)
            cutoff = (now or _now()) - _dt.timedelta(hours=self.posted_within_hours)
            if latest is None or latest < cutoff:
                return False
        if self.exclude_keywords:
            text = f"{job.title}\n{job.description or ''}".casefold()
            if any(word.casefold() in text for word in self.exclude_keywords):
                return False
        return True

    def match_details(self, job: Job) -> bool:
        if self.payment_verified and job.client_payment_verified is not True:
            return False
        if self.max_proposals is not None:
            if job.proposals is None or job.proposals > self.max_proposals:
                return False
        if self.min_client_spent is not None:
            if job.client_total_spent is None or job.client_total_spent < self.min_client_spent:
                return False
        if self.min_client_rating is not None:
            if job.client_rating is None or job.client_rating < self.min_client_rating:
                return False
        if self.client_countries:
            wanted = {c.casefold() for c in self.client_countries}
            if (job.client_country or "").casefold() not in wanted:
                return False
        return True

    def matches(self, job: Job, *, now: _dt.datetime | None = None) -> bool:
        return self.match_listing(job, now=now) and self.match_details(job)

    def apply(self, jobs: Iterable[Job], *, now: _dt.datetime | None = None) -> list[Job]:
        return [job for job in jobs if self.matches(job, now=now)]
