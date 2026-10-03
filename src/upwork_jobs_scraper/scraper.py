"""Scrape Upwork jobs through the ScrapeUnblocker ``getPageSource`` API.

ScrapeUnblocker loads each Upwork page in a real browser and returns its HTML;
:mod:`upwork_jobs_scraper.parsing` reads the data Upwork embeds in it. Three
public page types are used:

* **Job search** - any keywords, paged 10/20/50 at a time, with the filters a
  signed-out visitor may use (job type, experience level, project length,
  client hire history) and sorting by relevance or newest.
* **Skill job feeds** - ``/freelance-jobs/<skill>/``: recent jobs for one skill
  plus the skill's open-job count and related skills.
* **Job pages** - full details: client location, spend, hires, rating and
  payment verification, proposals and interviews, requirements, category.

Timeouts, transient API errors and pages without Upwork data are retried with
doubling backoff.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .filters import JobFilter
from .models import Job, SearchPage, SkillPage
from .parsing import (
    JobNotFoundError,
    SkillNotFoundError,
    UpworkError,
    UpworkParseError,
    parse_job_page,
    parse_search_page,
    parse_skill_page,
)
from .urls import PER_PAGE_OPTIONS, SearchQuery, job_url, skill_slug, skill_url

# A US route sees Upwork the way a US visitor does.
DEFAULT_PROXY_COUNTRY = "US"


def _transient_errors() -> tuple[type[BaseException], ...]:
    """Best-effort tuple of ScrapeUnblocker exceptions worth retrying.

    Imported lazily so the package is usable (and unit-testable) even when the
    ``scrapeunblocker`` SDK is not installed.
    """
    try:
        from scrapeunblocker import (  # type: ignore
            BlockedError,
            BrowserTimeoutError,
            RateLimitError,
            ScrapeTimeoutError,
            ServerError,
            UpstreamOutageError,
        )
        from scrapeunblocker import (
            ConnectionError as SUConnectionError,
        )
    except Exception:  # pragma: no cover - depends on SDK availability
        return ()
    return (
        UpstreamOutageError,
        RateLimitError,
        ScrapeTimeoutError,
        BrowserTimeoutError,
        BlockedError,
        ServerError,
        SUConnectionError,
    )


def is_not_found(error: BaseException) -> bool:
    """True when the API reports that the target page answered 404.

    Upwork answers 404 for unknown job ids and skill slugs; the SDK raises its
    not-found error (status code 404) for both.
    """
    return getattr(error, "status_code", None) == 404


def make_query(
    query: str = "",
    *,
    sort: str = "relevance",
    job_type: str | None = None,
    experience: Iterable[str] = (),
    duration: Iterable[str] = (),
    client_hires: Iterable[str] = (),
    per_page: int = 10,
    page: int = 1,
    params: Iterable[tuple[str, str]] = (),
) -> SearchQuery:
    """Build a :class:`SearchQuery` from friendly options."""
    return SearchQuery(
        query=(query or "").strip(),
        sort=sort,
        job_type=job_type,
        experience=tuple(experience),
        duration=tuple(duration),
        client_hires=tuple(client_hires),
        per_page=per_page,
        page=page,
        extra=tuple(params),
    )


def _per_page_for(limit: int, filtered: bool) -> int:
    if filtered:  # some results will be dropped, so fetch big pages
        return PER_PAGE_OPTIONS[-1]
    return next((n for n in PER_PAGE_OPTIONS if n >= limit), PER_PAGE_OPTIONS[-1])


class UpworkScraper:
    """Scrape Upwork job search results, skill job feeds and job pages.

    Args:
        api_key: ScrapeUnblocker key. If omitted, the SDK reads
            ``SCRAPEUNBLOCKER_KEY`` from the environment.
        client: A pre-built client (or any object exposing
            ``get_page_source(url, proxy_country=...)``). Mainly for testing.
        proxy_country: Country to route requests through (default ``"US"``).
        retries: Extra attempts per page on transient failures.
        backoff: Seconds before the first retry; doubles on every further retry.
        max_backoff: Upper bound for a single wait between retries.
        timeout: Per-request timeout passed to the SDK client.
        workers: Job pages fetched in parallel by :meth:`enrich`.
        transient_errors: Exception classes treated as retryable. Defaults to
            the ScrapeUnblocker transient set.
        on_retry: Optional callback ``(attempt, delay_seconds, error)`` invoked
            before every retry (handy for progress output).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        proxy_country: str | None = DEFAULT_PROXY_COUNTRY,
        retries: int = 3,
        backoff: float = 5.0,
        max_backoff: float = 60.0,
        timeout: float = 180.0,
        workers: int = 3,
        transient_errors: Sequence[type[BaseException]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_retry: Callable[[int, float, BaseException], None] | None = None,
    ) -> None:
        if client is None:
            from scrapeunblocker import Client  # local import: optional dep

            client = Client(api_key=api_key, timeout=timeout)
        self._client = client
        self.proxy_country = proxy_country
        self.retries = max(0, int(retries))
        self.backoff = float(backoff)
        self.max_backoff = float(max_backoff)
        self.workers = max(1, int(workers))
        self.on_retry = on_retry
        transient = tuple(transient_errors) if transient_errors is not None else _transient_errors()
        self._transient = (*transient, UpworkParseError)
        self._sleep = sleep
        self._lock = threading.Lock()
        self.requests_made = 0

    # ------------------------------------------------------------------ #
    # Fetching
    # ------------------------------------------------------------------ #

    def _fetch(
        self,
        url: str,
        parse: Callable[[str], Any],
        not_found: Callable[[], UpworkError] | None = None,
    ) -> Any:
        attempt = 0
        while True:
            try:
                with self._lock:
                    self.requests_made += 1
                html = self._client.get_page_source(url, proxy_country=self.proxy_country)
                return parse(html if isinstance(html, str) else "")
            except Exception as exc:
                if not_found is not None and is_not_found(exc):
                    raise not_found() from exc
                if not isinstance(exc, self._transient) or attempt >= self.retries:
                    raise
                attempt += 1
                delay = min(self.backoff * 2 ** (attempt - 1), self.max_backoff)
                if self.on_retry is not None:
                    self.on_retry(attempt, delay, exc)
                self._sleep(delay)

    def fetch_search_page(self, query: SearchQuery | str) -> SearchPage:
        """Fetch and parse one page of job search results (a query or a search URL).

        Raises:
            LoginRequiredError: the search uses a filter Upwork keeps behind its login.
        """
        if isinstance(query, str):
            query = SearchQuery.from_url(query)
        url = query.to_url()
        return self._fetch(url, lambda html: parse_search_page(html, url=url, query=query.query))

    def skill(self, skill: str) -> SkillPage:
        """Fetch a skill's job feed (one request): recent jobs, open-job count, related skills.

        ``skill`` is a slug (``web-scraping``), a name (``Web Scraping``) or a feed URL.

        Raises:
            SkillNotFoundError: Upwork has no job feed for this skill.
        """
        slug = skill_slug(skill)
        url = skill_url(slug)

        def missing() -> UpworkError:
            return SkillNotFoundError(f"Upwork has no job feed for skill {slug!r}: {url}")

        return self._fetch(url, lambda html: parse_skill_page(html, url=url, skill=slug), missing)

    def job(self, job: str) -> Job:
        """Fetch one job page by id (``~02...``), numeric uid or URL.

        Raises:
            JobNotFoundError: the job does not exist or is not public any more.
        """
        url = job_url(job)

        def missing() -> UpworkError:
            return JobNotFoundError(f"job not found: {url}")

        return self._fetch(url, lambda html: parse_job_page(html, url=url), missing)

    # ------------------------------------------------------------------ #
    # Collecting
    # ------------------------------------------------------------------ #

    def search(
        self,
        query: str | None = None,
        *,
        url: str | None = None,
        limit: int = 50,
        max_pages: int | None = None,
        job_filter: JobFilter | None = None,
        seen: set[str] | None = None,
        on_page: Callable[[SearchPage], None] | None = None,
        **options: Any,
    ) -> list[Job]:
        """Search Upwork jobs and return up to ``limit`` of them, paging as needed.

        Give ``query`` keywords plus any search options - ``sort`` (``relevance``
        or ``newest``), ``job_type`` (``hourly``/``fixed``), ``experience``,
        ``duration``, ``client_hires``, ``per_page`` (10/20/50, default: picked
        from ``limit``) and ``params`` (raw ``(key, value)`` URL parameters) -
        or a search ``url`` copied from the browser.

        Args:
            limit: Maximum number of jobs to return.
            max_pages: Hard cap on the number of pages requested.
            job_filter: Listing-level conditions (see :class:`JobFilter`); jobs
                that fail them do not count towards ``limit``.
            seen: Shared set of job ids; ids already in it are skipped. Pass the
                same set to several calls to de-duplicate across searches.
            on_page: Callback invoked with every fetched :class:`SearchPage`.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if url is not None:
            if query is not None or options:
                raise ValueError("pass either url or query/search options, not both")
            search_query = SearchQuery.from_url(url)
        else:
            if options.get("per_page") is None:
                options["per_page"] = _per_page_for(limit, job_filter is not None)
            search_query = make_query(query or "", **options)
        seen = seen if seen is not None else set()
        own: set[str] = set()
        out: list[Job] = []
        page_no = search_query.page
        pages = 0
        while len(out) < limit and (max_pages is None or pages < max_pages):
            page = self.fetch_search_page(search_query.with_page(page_no))
            pages += 1
            if on_page is not None:
                on_page(page)
            fresh = [job for job in page.jobs if job.job_id not in own]
            own.update(job.job_id for job in fresh)
            for job in fresh:
                if job.job_id in seen:
                    continue
                seen.add(job.job_id)
                if job_filter is not None and not job_filter.match_listing(job):
                    continue
                out.append(job)
                if len(out) >= limit:
                    break
            if not fresh or len(page.jobs) < page.per_page:
                break  # last page (or Upwork repeated a page)
            if page.total is not None and page_no * page.per_page >= page.total:
                break
            page_no += 1
        return out

    def skill_jobs(
        self,
        skill: str,
        *,
        limit: int | None = None,
        job_filter: JobFilter | None = None,
        seen: set[str] | None = None,
        on_page: Callable[[SkillPage], None] | None = None,
    ) -> list[Job]:
        """Jobs from one skill's feed (one request), optionally filtered and capped."""
        page = self.skill(skill)
        if on_page is not None:
            on_page(page)
        seen = seen if seen is not None else set()
        out: list[Job] = []
        for job in page.jobs:
            if limit is not None and len(out) >= limit:
                break
            if job.job_id in seen:
                continue
            seen.add(job.job_id)
            if job_filter is not None and not job_filter.match_listing(job):
                continue
            out.append(job)
        return out

    def enrich(
        self,
        jobs: Iterable[Job],
        *,
        on_error: Callable[[Job, BaseException], None] | None = None,
    ) -> list[Job]:
        """Fill every job in with the details from its own page (one request per job).

        Jobs whose page cannot be read (closed, private, or still failing after
        the retries) are returned unchanged with ``details_fetched=False``;
        ``on_error`` is called for each of them.
        """
        jobs = list(jobs)
        recoverable = (UpworkError, *self._transient)

        def one(job: Job) -> Job:
            try:
                return job.merged(self.job(job.job_id))
            except recoverable as exc:
                if on_error is not None:
                    on_error(job, exc)
                return job

        if self.workers == 1 or len(jobs) < 2:
            return [one(job) for job in jobs]
        with ThreadPoolExecutor(max_workers=min(self.workers, len(jobs))) as pool:
            return list(pool.map(one, jobs))

    def collect(
        self,
        *,
        queries: Iterable[str] = (),
        skills: Iterable[str] = (),
        urls: Iterable[str] = (),
        limit: int = 50,
        details: bool = False,
        job_filter: JobFilter | None = None,
        seen: set[str] | None = None,
        max_pages: int | None = None,
        on_page: Callable[[Any], None] | None = None,
        on_error: Callable[[Job, BaseException], None] | None = None,
        **search_options: Any,
    ) -> list[Job]:
        """Run several searches and skill feeds, de-duplicate, then optionally add details.

        ``limit`` applies to every query, URL and skill separately. Job pages are
        fetched when ``details`` is set or when ``job_filter`` has client-level
        conditions; those conditions are applied afterwards.
        """
        seen = seen if seen is not None else set()
        jobs: list[Job] = []
        for query in queries:
            jobs += self.search(
                query,
                limit=limit,
                max_pages=max_pages,
                job_filter=job_filter,
                seen=seen,
                on_page=on_page,
                **search_options,
            )
        for url in urls:
            jobs += self.search(
                url=url,
                limit=limit,
                max_pages=max_pages,
                job_filter=job_filter,
                seen=seen,
                on_page=on_page,
            )
        for skill in skills:
            jobs += self.skill_jobs(
                skill, limit=limit, job_filter=job_filter, seen=seen, on_page=on_page
            )
        if details or (job_filter is not None and job_filter.needs_details):
            jobs = self.enrich(jobs, on_error=on_error)
            if job_filter is not None:
                jobs = [job for job in jobs if job_filter.match_details(job)]
        return jobs
