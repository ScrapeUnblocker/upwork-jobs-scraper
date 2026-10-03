"""Scrape Upwork job postings into clean JSON.

Powered by the ScrapeUnblocker ``getPageSource`` API
(https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).

Quick start::

    from upwork_jobs_scraper import UpworkScraper

    scraper = UpworkScraper()  # reads SCRAPEUNBLOCKER_KEY from the environment
    jobs = scraper.search("web scraping", sort="newest", limit=20)
    for job in jobs:
        print(job.title, job.job_type, job.fixed_budget or job.hourly_max, job.url)
"""

from __future__ import annotations

from .filters import JobFilter
from .models import Job, RelatedSkill, SearchPage, SkillPage
from .parsing import (
    JobNotFoundError,
    LoginRequiredError,
    SkillNotFoundError,
    UpworkError,
    UpworkParseError,
    parse_job_page,
    parse_search_page,
    parse_skill_page,
)
from .scraper import UpworkScraper, make_query
from .urls import SearchQuery, job_id_from, job_url, skill_slug, skill_url
from .watch import SeenJobs

__version__ = "0.1.0"

__all__ = [
    "Job",
    "JobFilter",
    "JobNotFoundError",
    "LoginRequiredError",
    "RelatedSkill",
    "SearchPage",
    "SearchQuery",
    "SeenJobs",
    "SkillNotFoundError",
    "SkillPage",
    "UpworkError",
    "UpworkParseError",
    "UpworkScraper",
    "__version__",
    "job_id_from",
    "job_url",
    "make_query",
    "parse_job_page",
    "parse_search_page",
    "parse_skill_page",
    "skill_slug",
    "skill_url",
]
