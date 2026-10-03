"""Shared helpers: synthetic Upwork pages and a fake ScrapeUnblocker client.

Upwork pages carry their data as a Nuxt ``__NUXT_DATA__`` payload (devalue
format). :func:`encode` produces that format from plain Python data, so the
tests build small pages with the same structure Upwork serves, without
shipping third-party job postings.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit


def encode(value: Any) -> str:
    """Flatten ``value`` into a devalue array, wrapped like Nuxt's root state."""
    table: list[Any] = [["ShallowReactive", 1]]

    def add(item: Any) -> int:
        index = len(table)
        table.append(None)
        if isinstance(item, dict):
            table[index] = {k: add(v) for k, v in item.items()}
        elif isinstance(item, list):
            table[index] = [add(v) for v in item]
        elif item is None:
            table[index] = None
        else:
            table[index] = item
        return index

    add(value)
    return json.dumps(table)


def nuxt_html(state: dict[str, Any], *, title: str = "Upwork") -> str:
    return (
        f"<html><head><title>{title}</title></head><body><div id='__nuxt'></div>"
        '<script type="application/json" data-nuxt-data="nuxt-app" data-ssr="true" '
        f'id="__NUXT_DATA__">{encode(state)}</script></body></html>'
    )


LOGIN_HTML = (
    "<html><head><title>\n   Upwork Login - Log in to your Upwork account\n  </title></head>"
    "<body>login</body></html>"
)


def cipher(n: int) -> str:
    return f"~0221000000000000{n:04d}"


def search_job(n: int, **overrides: Any) -> dict[str, Any]:
    """One entry of ``vuex.jobsSearch.jobs`` (hourly by default)."""
    job = {
        "uid": f"21000000000000{n:04d}",
        "ciphertext": cipher(n),
        "title": f'<span class="highlight">Python</span> job {n}',
        "description": f'Build a <span class="highlight">Python</span> tool &amp; more ({n})',
        "createdOn": "2026-10-01T10:00:00.000Z",
        "publishedOn": "2026-10-01T10:05:00.000Z",
        "renewedOn": None,
        "type": 2,
        "durationLabel": "1 to 3 months",
        "engagement": "usnuxt_Engagement_421.partTime",
        "amount": {"amount": 0},
        "client": {"location": {"country": None}, "isPaymentVerified": False},
        "tierText": "jsn_Expert_207",
        "attrs": [
            {"prettyName": "Python", "prefLabel": "Python", "freeText": None},
            {"prettyName": "Web Scraping", "prefLabel": "Web Scraping", "freeText": None},
        ],
        "hourlyBudget": {"min": 30, "max": 60},
        "weeklyBudget": {"amount": 0},
    }
    job.update(overrides)
    return job


def fixed_search_job(n: int, budget: float = 500, **overrides: Any) -> dict[str, Any]:
    return search_job(
        n,
        type=1,
        engagement=None,
        amount={"amount": budget},
        hourlyBudget={"min": 0, "max": 0},
        tierText="jsn_Intermediate_206",
        durationLabel="Less than 1 month",
        **overrides,
    )


def search_html(
    jobs: list[dict[str, Any]],
    *,
    total: int | None = None,
    page: int = 1,
    per_page: int = 10,
    q: str = "python",
) -> str:
    state = {
        "serverRendered": True,
        "path": f"/nx/search/jobs/?q={q}",
        "vuex": {
            "jobsSearch": {
                "status": {"loading": False, "loaded": True, "failed": False},
                "jobs": jobs,
                "paging": {
                    "total": len(jobs) if total is None else total,
                    "offset": (page - 1) * per_page,
                    "count": per_page,
                },
                "currentPage": page,
                "jobsPerPage": per_page,
                "searchQueryCache": {"q": q},
            }
        },
    }
    return nuxt_html(state, title="Search Freelance Jobs on Upwork")


def feed_job(n: int, **overrides: Any) -> dict[str, Any]:
    """One entry of a skill feed's ``jobs`` list (fixed price by default)."""
    job = {
        "title": f"Feed job {n}",
        "description": f"Feed description {n}",
        "createdOn": "2026-09-30T08:00:00+0000",
        "ciphertext": cipher(n),
        "type": 1,
        "ontologySkills": [{"prefLabel": "Data Scraping", "slug": "data-scraping"}],
        "engagement": None,
        "amount": {"currencyCode": "USD", "amount": 250},
        "maxAmount": {"amount": None},
        "durationLabel": "Less than 1 month",
        "contractorTier": 1,
        "renewedOn": None,
        "ago": "3 days ago",
        "url": f"/freelance-jobs/apply/Feed-job-{n}_{cipher(n)}/",
    }
    job.update(overrides)
    return job


def skill_html(
    jobs: list[dict[str, Any]],
    *,
    slug: str = "web-scraping",
    name: str = "Web Scraping",
    total: int = 317,
) -> str:
    feed = {
        "jobs": jobs,
        "jobsCount": None,
        "totalJobs": total,
        "searchParams": {"paging": "0;30", "sort": "relevance desc"},
        "skillRoute": {"name": "freelance_jobs_skill_base_page", "params": {"skill": slug}},
        "modifier": name,
        "prettySkillName": name,
        "relatedJobs": [
            {
                "url": "https://www.upwork.com/freelance-jobs/data-scraping/",
                "urlPath": "/freelance-jobs/data-scraping/",
                "title": "Web Data Scraping jobs",
                "description": "Browse 3,472 open jobs and land a remote Web Data Scraping job.",
                "type": "related",
                "target": "FREELANCE-JOBS-SKILL",
            },
            {
                "url": "https://www.upwork.com/hire/web-scrapers/",
                "urlPath": "/hire/web-scrapers/",
                "title": "Web Scrapers",
                "description": None,
            },
        ],
    }
    state = {
        "data": {"layout-visitor": {}, "options:asyncdata:abc123": feed},
        "state": {},
        "path": f"/freelance-jobs/{slug}/",
    }
    return nuxt_html(state, title=f"{name} Freelance Jobs")


def job_details(n: int, *, job: dict[str, Any] | None = None, **buyer: Any) -> dict[str, Any]:
    """A job page's ``vuex.jobDetails`` (an hourly job from a reviewed US client)."""
    raw_job = {
        "status": 1,
        "category": {"name": "Scripts & Utilities", "urlSlug": "scripts-utilities"},
        "categoryGroup": {"name": "Web, Mobile & Software Dev", "urlSlug": "web-dev"},
        "budget": {"amount": 0, "currencyCode": "USD"},
        "postedOn": "2026-10-01T10:00:00.000Z",
        "publishTime": "2026-10-01T10:05:00.000Z",
        "workload": "Less than 30 hrs/week",
        "engagementDuration": {"label": "1 to 3 months", "weeks": 9},
        "extendedBudgetInfo": {
            "hourlyBudgetMin": 30,
            "hourlyBudgetMax": 60,
            "hourlyBudgetType": "MANUAL",
        },
        "contractorTier": 3,
        "description": f"Full description of job {n}.",
        "clientActivity": {
            "lastBuyerActivity": "2026-10-02T09:00:00.000Z",
            "totalApplicants": 12,
            "totalHired": 0,
            "totalInvitedToInterview": 2,
            "unansweredInvites": 1,
            "invitationsSent": 3,
            "numberOfPositionsToHire": 1,
        },
        "uid": f"21000000000000{n:04d}",
        "title": f"Python job {n}",
        "type": 2,
        "ciphertext": cipher(n),
        "numberOfPositionsToHire": 1,
        "isContractToHire": False,
        "qualifications": {
            "countries": ["United States"],
            "minJobSuccessScore": 90,
            "localMarket": True,
        },
        "durationLabel": "1 to 3 months",
    }
    raw_job.update(job or {})
    raw_buyer = {
        "isEnterprise": False,
        "isPaymentMethodVerified": True,
        "stats": {
            "totalAssignments": 7,
            "activeAssignmentsCount": 1,
            "hoursCount": 120,
            "feedbackCount": 5,
            "score": 4.9,
            "totalJobsWithHires": 6,
            "totalCharges": {"amount": 12500.5},
        },
        "location": {
            "countryTimezone": "America/Chicago (UTC-05:00)",
            "city": "Austin ",
            "country": "USA",
        },
        "company": {
            "contractDate": "2021-04-15T00:00:00.000Z",
            "profile": {"industry": "Tech & IT", "size": 2},
        },
        "isTopClient": False,
    }
    raw_buyer.update(buyer)
    return {
        "job": raw_job,
        "buyer": raw_buyer,
        "sands": {
            "occupation": {"prefLabel": "Scripting & Automation"},
            "ontologySkills": [
                {
                    "name": "Scripting & Automation Deliverables",
                    "children": [{"name": "Web Scraping", "relevance": "MANDATORY"}],
                }
            ],
            "additionalSkills": [
                {"name": "Python", "isFreeText": False},
                {"name": "Web Scraping", "isFreeText": False},
                {"name": "Google Sheets API", "isFreeText": True},
            ],
        },
    }


def job_html(details: dict[str, Any]) -> str:
    state = {"vuex": {"jobDetails": details}, "path": "/freelance-jobs/apply/Python-job_~02/"}
    return nuxt_html(state, title="Python job - Freelance Job")


def unavailable_job_html() -> str:
    """What Upwork serves for a job that is no longer public: the shell, no job."""
    return job_html({"job": None, "buyer": None, "sands": None})


class NotFound(Exception):
    """Mimics the SDK's not-found error (HTTP 404 from the target page)."""

    status_code = 404


class FakeClient:
    """Stands in for ``scrapeunblocker.Client``; ``responder(url, call_no)`` returns HTML."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[tuple[str, str | None]] = []

    def get_page_source(self, url: str, proxy_country: str | None = None):
        self.calls.append((url, proxy_country))
        result = self.responder(url, len(self.calls))
        if isinstance(result, BaseException):
            raise result
        return result


def url_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)
