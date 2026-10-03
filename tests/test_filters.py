from __future__ import annotations

import datetime as dt

from upwork_jobs_scraper.filters import JobFilter
from upwork_jobs_scraper.models import Job

NOW = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.timezone.utc)


def make_job(**kwargs) -> Job:
    base = dict(job_id="~021", title="Scrape a site", url="https://www.upwork.com/jobs/~021")
    base.update(kwargs)
    return Job(**base)


def test_empty_filter_keeps_everything():
    f = JobFilter()
    assert f.matches(make_job(), now=NOW)
    assert not f.needs_details


def test_min_fixed_budget_only_affects_fixed_jobs():
    f = JobFilter(min_fixed_budget=500)
    assert not f.match_listing(make_job(job_type="fixed", fixed_budget=100))
    assert f.match_listing(make_job(job_type="fixed", fixed_budget=500))
    assert f.match_listing(make_job(job_type="hourly", hourly_max=20))


def test_min_hourly_rate_uses_top_of_range():
    f = JobFilter(min_hourly_rate=40)
    assert not f.match_listing(make_job(job_type="hourly", hourly_min=15, hourly_max=35))
    assert f.match_listing(make_job(job_type="hourly", hourly_min=30, hourly_max=50))
    assert f.match_listing(make_job(job_type="hourly", hourly_min=45))
    assert f.match_listing(make_job(job_type="hourly"))  # no posted rate: kept
    assert f.match_listing(make_job(job_type="fixed", fixed_budget=10))


def test_posted_within_hours_counts_renewals():
    f = JobFilter(posted_within_hours=24)
    assert f.match_listing(make_job(posted_at="2026-10-03T01:00:00Z"), now=NOW)
    assert not f.match_listing(make_job(posted_at="2026-10-01T01:00:00Z"), now=NOW)
    renewed = make_job(posted_at="2026-09-01T01:00:00Z", renewed_at="2026-10-03T08:00:00Z")
    assert f.match_listing(renewed, now=NOW)
    assert not f.match_listing(make_job(), now=NOW)  # unknown date


def test_exclude_keywords_case_insensitive():
    f = JobFilter(exclude_keywords=("WordPress", " ", "unpaid"))
    assert f.exclude_keywords == ("WordPress", "unpaid")
    assert not f.match_listing(make_job(title="Fix my wordpress site"))
    assert not f.match_listing(make_job(description="This is an UNPAID test"))
    assert f.match_listing(make_job(title="Python scraper"))


def test_client_level_conditions():
    f = JobFilter(
        payment_verified=True,
        max_proposals=10,
        min_client_spent=1000,
        min_client_rating=4.5,
        client_countries=("USA", "Canada"),
    )
    assert f.needs_details
    assert f.client_countries == ("United States", "Canada")
    good = make_job(
        client_payment_verified=True,
        proposals=5,
        client_total_spent=2500.0,
        client_rating=4.8,
        client_country="United States",
    )
    assert f.match_details(good)
    for change in [
        {"client_payment_verified": False},
        {"proposals": 11},
        {"proposals": None},
        {"client_total_spent": 999.0},
        {"client_rating": None},
        {"client_rating": 4.0},
        {"client_country": "India"},
        {"client_country": None},
    ]:
        assert not f.match_details(make_job(**{**good.to_dict(), **change})), change


def test_listing_only_drops_client_conditions():
    f = JobFilter(min_fixed_budget=100, payment_verified=True, client_countries=("Canada",))
    listing = f.listing_only()
    assert listing.min_fixed_budget == 100
    assert not listing.needs_details
    assert listing.match_details(make_job())


def test_apply():
    f = JobFilter(min_fixed_budget=100)
    jobs = [
        make_job(job_type="fixed", fixed_budget=50),
        make_job(job_type="fixed", fixed_budget=150),
    ]
    assert [j.fixed_budget for j in f.apply(jobs, now=NOW)] == [150]
