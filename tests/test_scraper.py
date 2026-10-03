from __future__ import annotations

import pytest
from conftest import (
    LOGIN_HTML,
    FakeClient,
    NotFound,
    cipher,
    feed_job,
    fixed_search_job,
    job_details,
    job_html,
    search_html,
    search_job,
    skill_html,
    unavailable_job_html,
    url_params,
)

from upwork_jobs_scraper.filters import JobFilter
from upwork_jobs_scraper.parsing import (
    JobNotFoundError,
    LoginRequiredError,
    SkillNotFoundError,
    UpworkParseError,
)
from upwork_jobs_scraper.scraper import UpworkScraper, make_query


class Transient(Exception):
    pass


def make_scraper(responder, **kwargs):
    client = FakeClient(responder)
    kwargs.setdefault("transient_errors", (Transient,))
    kwargs.setdefault("workers", 1)
    scraper = UpworkScraper(client=client, sleep=lambda _s: None, **kwargs)
    return scraper, client


def paged(ids_by_page: dict[int, list[int]], *, total: int, per_page: int | None = None):
    """Responder serving search pages of job numbers by ``page`` parameter."""

    def responder(url, _n):
        params = url_params(url)
        page = int(params.get("page", ["1"])[0])
        size = per_page or int(params.get("per_page", ["10"])[0])
        jobs = [search_job(i) for i in ids_by_page.get(page, [])]
        return search_html(jobs, total=total, page=page, per_page=size)

    return responder


# --------------------------------------------------------------------------- #
# Fetching and retries
# --------------------------------------------------------------------------- #


def test_fetch_search_page_uses_proxy_country():
    scraper, client = make_scraper(paged({1: [1, 2]}, total=2), proxy_country="GB")
    page = scraper.fetch_search_page(make_query("python"))
    assert len(page.jobs) == 2
    assert client.calls[0] == ("https://www.upwork.com/nx/search/jobs/?q=python", "GB")


def test_retries_transient_errors_with_backoff():
    delays = []
    good = search_html([search_job(1)])
    responses = [Transient("timeout"), "<html>interstitial</html>", good]
    scraper, client = make_scraper(
        lambda url, n: responses[n - 1],
        on_retry=lambda attempt, delay, exc: delays.append((attempt, delay, type(exc).__name__)),
        backoff=2,
    )
    page = scraper.fetch_search_page(make_query("python"))
    assert len(page.jobs) == 1
    assert delays == [(1, 2.0, "Transient"), (2, 4.0, "UpworkParseError")]
    assert len(client.calls) == 3 and scraper.requests_made == 3


def test_backoff_is_capped():
    delays = []
    scraper, _ = make_scraper(
        lambda url, n: Transient("down"),
        retries=4,
        backoff=10,
        max_backoff=25,
        on_retry=lambda a, d, e: delays.append(d),
    )
    with pytest.raises(Transient):
        scraper.fetch_search_page(make_query("python"))
    assert delays == [10.0, 20.0, 25.0, 25.0]


def test_gives_up_after_retries():
    scraper, client = make_scraper(lambda url, n: "<html>still blocked</html>", retries=2)
    with pytest.raises(UpworkParseError):
        scraper.fetch_search_page(make_query("python"))
    assert len(client.calls) == 3


def test_non_transient_errors_are_not_retried():
    scraper, client = make_scraper(lambda url, n: RuntimeError("bad key"))
    with pytest.raises(RuntimeError):
        scraper.fetch_search_page(make_query("python"))
    assert len(client.calls) == 1


def test_login_wall_is_not_retried():
    scraper, client = make_scraper(lambda url, n: LOGIN_HTML)
    with pytest.raises(LoginRequiredError):
        scraper.fetch_search_page(make_query("python", params=[("payment_verified", "1")]))
    assert len(client.calls) == 1


def test_job_not_found_from_404_and_from_empty_page():
    scraper, client = make_scraper(lambda url, n: NotFound("404"))
    with pytest.raises(JobNotFoundError):
        scraper.job("~021234567890123456789")
    assert len(client.calls) == 1
    scraper, _ = make_scraper(lambda url, n: unavailable_job_html())
    with pytest.raises(JobNotFoundError):
        scraper.job("https://www.upwork.com/jobs/~021234567890123456789")


def test_skill_not_found():
    scraper, client = make_scraper(lambda url, n: NotFound("404"))
    with pytest.raises(SkillNotFoundError):
        scraper.skill("Not A Real Skill")
    assert client.calls[0][0] == "https://www.upwork.com/freelance-jobs/not-a-real-skill/"


# --------------------------------------------------------------------------- #
# Search paging
# --------------------------------------------------------------------------- #


def test_search_picks_page_size_from_limit():
    scraper, client = make_scraper(paged({1: list(range(1, 21))}, total=200))
    jobs = scraper.search("python", limit=15)
    assert len(jobs) == 15
    assert url_params(client.calls[0][0])["per_page"] == ["20"]
    assert len(client.calls) == 1


def test_search_pages_until_limit():
    pages = {1: list(range(1, 11)), 2: list(range(11, 21)), 3: list(range(21, 31))}
    scraper, client = make_scraper(paged(pages, total=100))
    jobs = scraper.search("python", limit=25, per_page=10)
    assert len(jobs) == 25
    assert [url_params(u).get("page", ["1"])[0] for u, _ in client.calls] == ["1", "2", "3"]


def test_search_stops_at_total_and_short_pages():
    scraper, client = make_scraper(paged({1: list(range(1, 11)), 2: [11, 12]}, total=12))
    jobs = scraper.search("python", limit=100, per_page=10)
    assert len(jobs) == 12 and len(client.calls) == 2


def test_search_stops_when_upwork_repeats_a_page():
    scraper, client = make_scraper(paged({1: list(range(1, 11)), 2: list(range(1, 11))}, total=500))
    jobs = scraper.search("python", limit=100, per_page=10)
    assert len(jobs) == 10 and len(client.calls) == 2


def test_search_respects_max_pages():
    pages = {n: list(range(n * 10, n * 10 + 10)) for n in range(1, 6)}
    scraper, client = make_scraper(paged(pages, total=500))
    jobs = scraper.search("python", limit=100, per_page=10, max_pages=2)
    assert len(jobs) == 20 and len(client.calls) == 2


def test_search_dedupes_across_calls_with_shared_seen():
    scraper, _ = make_scraper(paged({1: [1, 2, 3]}, total=3))
    seen: set[str] = set()
    first = scraper.search("python", seen=seen)
    second = scraper.search("python", seen=seen)
    assert len(first) == 3 and second == []


def test_search_with_listing_filter_uses_big_pages():
    def responder(url, _n):
        jobs = [fixed_search_job(1, budget=50), fixed_search_job(2, budget=900), search_job(3)]
        return search_html(jobs, total=3, per_page=50)

    scraper, client = make_scraper(responder)
    jobs = scraper.search("python", limit=10, job_filter=JobFilter(min_fixed_budget=100))
    assert [j.job_id for j in jobs] == [cipher(2), cipher(3)]
    assert url_params(client.calls[0][0])["per_page"] == ["50"]


def test_search_from_url_keeps_its_filters():
    scraper, client = make_scraper(paged({1: [1]}, total=1))
    scraper.search(url="https://www.upwork.com/nx/search/jobs/?q=logo&t=1&sort=recency")
    params = url_params(client.calls[0][0])
    assert params["q"] == ["logo"] and params["t"] == ["1"] and params["sort"] == ["recency"]


def test_search_argument_validation():
    scraper, _ = make_scraper(paged({}, total=0))
    with pytest.raises(ValueError):
        scraper.search("python", limit=0)
    with pytest.raises(ValueError):
        scraper.search("python", url="https://www.upwork.com/nx/search/jobs/?q=x")
    with pytest.raises(ValueError):
        scraper.search("python", sort="cheapest")


# --------------------------------------------------------------------------- #
# Skill feeds, details and collecting
# --------------------------------------------------------------------------- #


def test_skill_jobs_limit_and_filter():
    jobs_html = skill_html([feed_job(1), feed_job(2, amount={"amount": 20}), feed_job(3)])
    scraper, client = make_scraper(lambda url, n: jobs_html)
    jobs = scraper.skill_jobs("web-scraping", limit=1, job_filter=JobFilter(min_fixed_budget=100))
    assert [j.job_id for j in jobs] == [cipher(1)]
    jobs = scraper.skill_jobs("web-scraping", job_filter=JobFilter(min_fixed_budget=100))
    assert [j.job_id for j in jobs] == [cipher(1), cipher(3)]


def by_kind(job_pages: dict[str, str] | None = None):
    """Responder: search pages, skill feeds and job pages by URL."""
    job_pages = job_pages or {}

    def responder(url, _n):
        if "/nx/search/jobs/" in url:
            return search_html([search_job(1), search_job(2)], total=2)
        if "/freelance-jobs/" in url:
            return skill_html([feed_job(2), feed_job(3)])
        job_id = url.rsplit("/", 1)[-1]
        return job_pages.get(job_id, job_html(job_details(int(job_id[-4:]))))

    return responder


def test_enrich_merges_details_and_keeps_failures():
    errors = []
    responder = by_kind({cipher(2): unavailable_job_html()})
    scraper, _ = make_scraper(responder)
    listing = scraper.search("python")
    enriched = scraper.enrich(listing, on_error=lambda job, exc: errors.append(job.job_id))
    first, second = enriched
    assert first.details_fetched and first.client_country == "United States"
    assert first.source == "search" and first.query == "python"  # provenance kept
    assert first.proposals == 12
    assert not second.details_fetched and second.client_country is None
    assert errors == [cipher(2)]


def test_enrich_in_parallel_keeps_order():
    scraper, client = make_scraper(by_kind(), workers=4)
    listing = scraper.search("python") + scraper.skill_jobs("web-scraping")
    enriched = scraper.enrich(listing)
    assert [j.job_id for j in enriched] == [cipher(1), cipher(2), cipher(2), cipher(3)]
    assert all(j.details_fetched for j in enriched)


def test_collect_dedupes_queries_and_skills():
    scraper, client = make_scraper(by_kind())
    jobs = scraper.collect(queries=["python"], skills=["web-scraping"], limit=10)
    assert [(j.job_id, j.source) for j in jobs] == [
        (cipher(1), "search"),
        (cipher(2), "search"),
        (cipher(3), "skill"),
    ]
    assert len(client.calls) == 2


def test_collect_fetches_details_for_client_filters():
    poor = job_details(2, isPaymentMethodVerified=False)
    scraper, client = make_scraper(by_kind({cipher(2): job_html(poor)}))
    jobs = scraper.collect(queries=["python"], job_filter=JobFilter(payment_verified=True))
    assert [j.job_id for j in jobs] == [cipher(1)]
    assert jobs[0].details_fetched
    assert len(client.calls) == 3  # 1 search + 2 job pages


def test_collect_details_flag():
    scraper, client = make_scraper(by_kind())
    jobs = scraper.collect(skills=["web-scraping"], details=True)
    assert all(j.details_fetched for j in jobs) and len(client.calls) == 3
