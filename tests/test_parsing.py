from __future__ import annotations

import pytest
from conftest import (
    LOGIN_HTML,
    cipher,
    feed_job,
    fixed_search_job,
    job_details,
    job_html,
    search_html,
    search_job,
    skill_html,
    unavailable_job_html,
)

from upwork_jobs_scraper.parsing import (
    JobNotFoundError,
    LoginRequiredError,
    UpworkParseError,
    clean_text,
    experience_from_tier,
    iso_utc,
    normalize_country,
    normalize_workload,
    parse_job_page,
    parse_search_page,
    parse_skill_page,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_clean_text_strips_highlights_and_entities():
    raw = '<span class="highlight">Web</span>   Scraping &amp; data\n\n\n\nline  two '
    assert clean_text(raw) == "Web Scraping & data\n\nline two"
    assert clean_text("  ") is None and clean_text(None) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-01T10:05:00.123Z", "2026-10-01T10:05:00Z"),
        ("2026-09-29T08:06:52+0000", "2026-09-29T08:06:52Z"),
        ("2026-09-29T10:06:52+02:00", "2026-09-29T08:06:52Z"),
        ("2026-09-29", "2026-09-29T00:00:00Z"),
        ("yesterday", None),
        (None, None),
    ],
)
def test_iso_utc(value, expected):
    assert iso_utc(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("usnuxt_Engagement_421.partTime", "Less than 30 hrs/week"),
        ("usnuxt_Engagement_421.fullTime", "More than 30 hrs/week"),
        ("30+ hrs/week", "More than 30 hrs/week"),
        ("Less than 30 hrs/week", "Less than 30 hrs/week"),
        ("As needed", "As needed"),
        (None, None),
    ],
)
def test_normalize_workload(value, expected):
    assert normalize_workload(value) == expected


def test_experience_and_country():
    assert experience_from_tier("jsn_EntryLevel_205") == "Entry level"
    assert experience_from_tier("jsn_Intermediate_206") == "Intermediate"
    assert experience_from_tier(3) == "Expert"
    assert experience_from_tier(None) is None
    assert normalize_country("USA") == "United States"
    assert normalize_country("CAN") == "Canada"
    assert normalize_country("United Kingdom") == "United Kingdom"
    assert normalize_country("") is None


# --------------------------------------------------------------------------- #
# Search pages
# --------------------------------------------------------------------------- #


def test_parse_search_page():
    html = search_html([search_job(1), fixed_search_job(2, budget=750)], total=40, per_page=20)
    page = parse_search_page(html, url="https://example/search")
    assert (page.query, page.page, page.per_page, page.total) == ("python", 1, 20, 40)
    hourly, fixed = page.jobs
    assert hourly.job_id == cipher(1) and hourly.uid == "210000000000000001"
    assert hourly.url == f"https://www.upwork.com/jobs/{cipher(1)}"
    assert hourly.title == "Python job 1"
    assert hourly.description == "Build a Python tool & more (1)"
    assert hourly.job_type == "hourly" and hourly.fixed_budget is None
    assert (hourly.hourly_min, hourly.hourly_max, hourly.currency) == (30.0, 60.0, "USD")
    assert hourly.experience_level == "Expert"
    assert hourly.workload == "Less than 30 hrs/week"
    assert hourly.skills == ["Python", "Web Scraping"]
    assert hourly.posted_at == "2026-10-01T10:05:00Z"
    assert hourly.source == "search" and hourly.query == "python"
    assert hourly.details_fetched is False and hourly.client_country is None
    assert fixed.job_type == "fixed" and fixed.fixed_budget == 750.0
    assert fixed.hourly_min is None and fixed.workload is None
    assert fixed.experience_level == "Intermediate"


def test_hourly_job_without_rate_has_no_currency():
    page = parse_search_page(search_html([search_job(1, hourlyBudget={"min": 0, "max": 0})]))
    job = page.jobs[0]
    assert job.hourly_min is None and job.hourly_max is None and job.currency is None


def test_search_page_skips_broken_entries():
    page = parse_search_page(search_html([search_job(1), {"title": "no id"}, "junk"]))
    assert [j.job_id for j in page.jobs] == [cipher(1)]


def test_search_page_login_wall():
    with pytest.raises(LoginRequiredError):
        parse_search_page(LOGIN_HTML)


@pytest.mark.parametrize(
    "html", ["<html>interstitial</html>", search_html([]).replace("jobsSearch", "x")]
)
def test_search_page_without_data(html):
    with pytest.raises(UpworkParseError):
        parse_search_page(html)


def test_empty_search_is_not_an_error():
    page = parse_search_page(search_html([], total=0))
    assert page.jobs == [] and page.total == 0


# --------------------------------------------------------------------------- #
# Skill feeds
# --------------------------------------------------------------------------- #


def test_parse_skill_page():
    hourly = feed_job(
        2, type=2, engagement="30+ hrs/week", amount={"amount": 0}, maxAmount={"amount": 45}
    )
    page = parse_skill_page(skill_html([feed_job(1), hourly]))
    assert (page.slug, page.name, page.total_jobs) == ("web-scraping", "Web Scraping", 317)
    assert page.url == "https://www.upwork.com/freelance-jobs/web-scraping/"
    fixed, hourly_job = page.jobs
    assert fixed.job_type == "fixed" and fixed.fixed_budget == 250.0 and fixed.currency == "USD"
    assert fixed.experience_level == "Entry level"
    assert fixed.skills == ["Data Scraping"]
    assert fixed.posted_at == "2026-09-30T08:00:00Z"
    assert fixed.source == "skill" and fixed.query == "web-scraping"
    assert hourly_job.hourly_max == 45.0 and hourly_job.hourly_min is None
    assert hourly_job.workload == "More than 30 hrs/week"
    assert len(page.related_skills) == 1
    related = page.related_skills[0]
    assert (related.slug, related.name, related.open_jobs) == (
        "data-scraping",
        "Web Data Scraping",
        3472,
    )


def test_skill_page_without_feed():
    with pytest.raises(UpworkParseError):
        parse_skill_page(search_html([search_job(1)]))


# --------------------------------------------------------------------------- #
# Job pages
# --------------------------------------------------------------------------- #


def test_parse_job_page():
    job = parse_job_page(job_html(job_details(7)))
    assert job.job_id == cipher(7) and job.title == "Python job 7"
    assert job.details_fetched is True and job.source == "job"
    assert job.job_type == "hourly" and (job.hourly_min, job.hourly_max) == (30.0, 60.0)
    assert job.experience_level == "Expert"
    assert (job.duration, job.duration_weeks) == ("1 to 3 months", 9)
    assert job.workload == "Less than 30 hrs/week"
    assert job.skills == ["Web Scraping", "Python", "Google Sheets API"]
    assert job.category == "Scripts & Utilities"
    assert job.category_group == "Web, Mobile & Software Dev"
    assert job.occupation == "Scripting & Automation"
    assert job.posted_at == "2026-10-01T10:05:00Z"
    assert (job.proposals, job.interviewing, job.invites_sent, job.hired) == (12, 2, 3, 0)
    assert job.unanswered_invites == 1 and job.positions == 1 and job.contract_to_hire is False
    assert job.client_last_active_at == "2026-10-02T09:00:00Z"
    assert job.preferred_countries == ["United States"] and job.min_job_success_score == 90
    assert job.client_country == "United States" and job.client_city == "Austin"
    assert job.client_timezone == "America/Chicago (UTC-05:00)"
    assert job.client_payment_verified is True
    assert (job.client_rating, job.client_reviews) == (4.9, 5)
    assert job.client_total_spent == 12500.5
    assert (job.client_hires, job.client_active_hires) == (7, 1)
    assert job.client_member_since == "2021-04-15"
    assert job.client_industry == "Tech & IT" and job.client_enterprise is False


def test_new_client_has_no_rating_and_zero_spend():
    details = job_details(
        3,
        stats={"feedbackCount": 0, "score": 0, "totalAssignments": 0, "totalCharges": None},
        isPaymentMethodVerified=False,
    )
    job = parse_job_page(job_html(details))
    assert job.client_rating is None and job.client_reviews == 0
    assert job.client_total_spent == 0.0 and job.client_payment_verified is False


def test_fixed_price_job_page():
    details = job_details(
        4,
        job={"type": 1, "budget": {"amount": 1200, "currencyCode": "USD"}, "workload": None},
    )
    job = parse_job_page(job_html(details))
    assert job.job_type == "fixed" and job.fixed_budget == 1200.0
    assert job.hourly_min is None and job.hourly_max is None


def test_unavailable_job():
    with pytest.raises(JobNotFoundError):
        parse_job_page(unavailable_job_html(), url="https://www.upwork.com/jobs/~02x")


def test_job_page_login_and_garbage():
    with pytest.raises(LoginRequiredError):
        parse_job_page(LOGIN_HTML)
    with pytest.raises(UpworkParseError):
        parse_job_page(search_html([search_job(1)]))
