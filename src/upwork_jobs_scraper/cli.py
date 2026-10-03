"""Command line interface: ``upwork-jobs-scraper search | skill | job | watch``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__
from .export import FORMATS, format_for, render, write
from .filters import JobFilter
from .models import Job, SearchPage, SkillPage
from .parsing import JobNotFoundError, LoginRequiredError, SkillNotFoundError, UpworkError
from .scraper import DEFAULT_PROXY_COUNTRY, UpworkScraper
from .urls import CLIENT_HIRES, DURATIONS, EXPERIENCE_LEVELS, JOB_TYPES, PER_PAGE_OPTIONS, SORTS
from .watch import SeenJobs

EPILOG = """examples:
  upwork-jobs-scraper search "web scraping" --sort newest --limit 20
  upwork-jobs-scraper search "python" "django" --type hourly --experience expert -o jobs.csv
  upwork-jobs-scraper search --sort newest --type fixed --min-fixed-budget 1000 --limit 100
  upwork-jobs-scraper skill web-scraping data-scraping --details -o feed.csv
  upwork-jobs-scraper job ~022097119470235197340
  upwork-jobs-scraper watch --skill web-scraping --query "scrapy" --state seen.json \\
      --payment-verified --max-proposals 15 -o new_jobs.jsonl --append
"""


def _str_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _choice_list(allowed: Sequence[str]):
    def parse(value: str) -> list[str]:
        items = [v.lower() for v in _str_list(value)]
        bad = [v for v in items if v not in allowed]
        if bad or not items:
            raise argparse.ArgumentTypeError(
                f"choose from {', '.join(allowed)} (comma-separated), got {value!r}"
            )
        return items

    return parse


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _non_negative(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return number


def _param(value: str) -> tuple[str, str]:
    key, sep, val = value.partition("=")
    if not sep or not key.strip():
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {value!r}")
    return key.strip(), val.strip()


def _request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--country",
        default=DEFAULT_PROXY_COUNTRY,
        help=f"country to route requests through (default {DEFAULT_PROXY_COUNTRY})",
    )
    parser.add_argument("--retries", type=int, default=3, help="retries per request (default 3)")
    parser.add_argument(
        "--workers", type=_positive, default=3, help="job pages fetched in parallel (default 3)"
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="no progress output on stderr")


def _output_args(parser: argparse.ArgumentParser, *, append: bool = True) -> None:
    parser.add_argument("-o", "--output", help="write to a file (.json, .jsonl or .csv)")
    parser.add_argument(
        "--format", choices=FORMATS, help="output format (default: from -o, else json)"
    )
    if append:
        parser.add_argument(
            "--append", action="store_true", help="append to an existing .jsonl/.csv file"
        )


def _search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sort", choices=list(SORTS), default="relevance", help="sort order")
    parser.add_argument("--type", dest="job_type", choices=list(JOB_TYPES), help="job type")
    parser.add_argument(
        "--experience",
        type=_choice_list(list(EXPERIENCE_LEVELS)),
        default=[],
        help="experience levels: " + ", ".join(EXPERIENCE_LEVELS),
    )
    parser.add_argument(
        "--duration",
        type=_choice_list(list(DURATIONS)),
        default=[],
        help="project length: week (<1 month), month (1-3), semester (3-6), ongoing (6+)",
    )
    parser.add_argument(
        "--client-hires",
        type=_choice_list(list(CLIENT_HIRES)),
        default=[],
        help="client's past hires: " + ", ".join(CLIENT_HIRES),
    )
    parser.add_argument(
        "--per-page",
        type=int,
        choices=PER_PAGE_OPTIONS,
        help="results per request (default: picked from --limit)",
    )
    parser.add_argument("--max-pages", type=_positive, help="hard cap on pages per query")
    parser.add_argument(
        "--param",
        dest="params",
        type=_param,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="raw Upwork search URL parameter; repeatable",
    )


def _filter_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "filters", "applied locally; the client filters fetch each job's page (one request/job)"
    )
    group.add_argument(
        "--details",
        action="store_true",
        help="fetch every job's page for client, proposal and requirement details",
    )
    group.add_argument(
        "--min-fixed-budget", type=_non_negative, help="drop fixed-price jobs below this (USD)"
    )
    group.add_argument(
        "--min-hourly-rate", type=_non_negative, help="drop hourly jobs topping out below this"
    )
    group.add_argument(
        "--posted-within", type=_non_negative, metavar="HOURS", help="only jobs this recent"
    )
    group.add_argument(
        "--exclude", type=_str_list, default=[], metavar="WORDS", help="drop jobs mentioning these"
    )
    group.add_argument(
        "--payment-verified", action="store_true", help="client has a verified payment method"
    )
    group.add_argument("--max-proposals", type=int, help="at most this many proposals so far")
    group.add_argument(
        "--min-client-spent", type=_non_negative, help="client has spent at least this (USD)"
    )
    group.add_argument("--min-client-rating", type=_non_negative, help="client rating (0-5)")
    group.add_argument(
        "--client-country",
        dest="client_countries",
        type=_str_list,
        default=[],
        metavar="COUNTRIES",
        help='client countries, comma-separated, e.g. "United States,Canada"',
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upwork-jobs-scraper",
        description="Scrape Upwork job postings into JSON/CSV via ScrapeUnblocker.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search jobs by keywords")
    search.add_argument(
        "queries",
        nargs="*",
        metavar="QUERY",
        help='keywords, e.g. "web scraping" (none: all jobs, e.g. with --sort newest)',
    )
    search.add_argument(
        "--url", dest="urls", action="append", default=[], help="an Upwork job search URL"
    )
    search.add_argument(
        "--limit", type=_positive, default=50, help="max jobs per query (default 50)"
    )
    _search_args(search)
    _filter_args(search)
    _output_args(search)
    _request_args(search)

    skill = sub.add_parser("skill", help="recent jobs from skill job feeds")
    skill.add_argument(
        "skills", nargs="+", metavar="SKILL", help="skill slug, name or feed URL, e.g. web-scraping"
    )
    skill.add_argument("--limit", type=_positive, help="max jobs per skill (default: whole feed)")
    skill.add_argument(
        "--related",
        action="store_true",
        help="list each skill's related skills and open-job counts instead of jobs",
    )
    _filter_args(skill)
    _output_args(skill)
    _request_args(skill)

    job = sub.add_parser("job", help="full details for one or more jobs")
    job.add_argument("jobs", nargs="+", metavar="JOB", help="job id (~02...), uid or job URL")
    _output_args(job, append=False)
    _request_args(job)

    watch = sub.add_parser("watch", help="only output jobs not seen on earlier runs")
    watch.add_argument(
        "--query", dest="queries", action="append", default=[], help="search keywords; repeatable"
    )
    watch.add_argument(
        "--skill", dest="skills", action="append", default=[], help="skill feed; repeatable"
    )
    watch.add_argument(
        "--url", dest="urls", action="append", default=[], help="job search URL; repeatable"
    )
    watch.add_argument(
        "--state",
        default="upwork_seen_jobs.json",
        help="file remembering seen jobs (default upwork_seen_jobs.json)",
    )
    watch.add_argument(
        "--baseline",
        action="store_true",
        help="record the current jobs as seen without outputting them",
    )
    watch.add_argument(
        "--limit", type=_positive, default=50, help="max jobs per query/skill (default 50)"
    )
    _search_args(watch)
    _filter_args(watch)
    _output_args(watch)
    _request_args(watch)
    return parser


def _job_filter(args: argparse.Namespace) -> JobFilter | None:
    job_filter = JobFilter(
        min_fixed_budget=args.min_fixed_budget,
        min_hourly_rate=args.min_hourly_rate,
        posted_within_hours=args.posted_within,
        exclude_keywords=tuple(args.exclude),
        payment_verified=args.payment_verified,
        max_proposals=args.max_proposals,
        min_client_spent=args.min_client_spent,
        min_client_rating=args.min_client_rating,
        client_countries=tuple(args.client_countries),
    )
    return None if job_filter == JobFilter() else job_filter


def _search_options(args: argparse.Namespace) -> dict[str, Any]:
    return dict(
        sort=args.sort,
        job_type=args.job_type,
        experience=args.experience,
        duration=args.duration,
        client_hires=args.client_hires,
        per_page=args.per_page,
        params=args.params,
    )


def _stdout(text: str) -> None:
    # Write UTF-8 bytes so job titles print on any console code page.
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - e.g. captured streams
        sys.stdout.write(text)


def _log(args: argparse.Namespace, message: str) -> None:
    if not args.quiet:
        print(message, file=sys.stderr)


def _emit(args: argparse.Namespace, jobs: list[Job], noun: str = "jobs") -> None:
    if args.output:
        path = write(jobs, args.output, args.format, append=getattr(args, "append", False))
        _log(args, f"Wrote {len(jobs)} {noun} to {path}")
    else:
        _stdout(render(jobs, format_for(None, args.format)))
        _log(args, f"{len(jobs)} {noun}")


def _on_page(args: argparse.Namespace):
    def callback(page: Any) -> None:
        if isinstance(page, SearchPage):
            total = f"{page.total} total" if page.total is not None else "total unknown"
            what = repr(page.query) if page.query else "(all jobs)"
            _log(args, f"  search {what} page {page.page}: {len(page.jobs)} jobs ({total})")
        elif isinstance(page, SkillPage):
            total = page.total_jobs if page.total_jobs is not None else "?"
            _log(args, f"  skill {page.slug}: {len(page.jobs)} recent jobs ({total} open)")

    return callback


def _on_error(args: argparse.Namespace):
    def callback(job: Job, exc: BaseException) -> None:
        _log(args, f"  no details for {job.job_id}: {exc}")

    return callback


def _run_related(args: argparse.Namespace, scraper: UpworkScraper) -> int:
    pages = [scraper.skill(skill) for skill in args.skills]
    if args.format == "json" or (args.output and format_for(args.output, args.format) == "json"):
        text = json.dumps(
            [
                {
                    "skill": p.slug,
                    "name": p.name,
                    "open_jobs": p.total_jobs,
                    "related": [r.to_dict() for r in p.related_skills],
                }
                for p in pages
            ],
            indent=2,
            ensure_ascii=False,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        else:
            _stdout(text + "\n")
        return 0
    lines = []
    for page in pages:
        lines.append(f"{page.name or page.slug} ({page.slug}): {page.total_jobs} open jobs")
        for rel in page.related_skills:
            count = rel.open_jobs if rel.open_jobs is not None else "?"
            lines.append(f"  {rel.slug:<36} {count:>7}  {rel.name}")
    _stdout("\n".join(lines) + "\n")
    return 0


def _run_watch(args: argparse.Namespace, scraper: UpworkScraper) -> int:
    store = SeenJobs(args.state)
    first_run = store.is_new_store
    job_filter = _job_filter(args)
    listing_filter = job_filter.listing_only() if job_filter else None
    listing = scraper.collect(
        queries=args.queries,
        skills=args.skills,
        urls=args.urls,
        limit=args.limit,
        job_filter=listing_filter,
        max_pages=args.max_pages,
        on_page=_on_page(args),
        **_search_options(args),
    )
    new = store.filter_new(listing)
    store.add(listing)
    if args.baseline:
        store.save()
        _log(args, f"Baseline: recorded {len(listing)} jobs in {args.state} ({len(store)} total)")
        return 0
    if new and (args.details or (job_filter is not None and job_filter.needs_details)):
        _log(args, f"Fetching details for {len(new)} new jobs")
        failed: list[Job] = []
        log_error = _on_error(args)

        def on_error(job: Job, exc: BaseException) -> None:
            failed.append(job)
            log_error(job, exc)

        new = scraper.enrich(new, on_error=on_error)
        # Hold these back and try again on the next run instead of reporting them twice.
        store.discard(failed)
        new = [job for job in new if job.details_fetched]
        if job_filter is not None:
            new = [job for job in new if job_filter.match_details(job)]
    _emit(args, new, "new jobs")
    store.save()
    if first_run:
        _log(args, "First run: every job counts as new. Use --baseline to start quietly.")
    return 0


def main(argv: Sequence[str] | None = None, *, scraper: UpworkScraper | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "watch" and not (args.queries or args.skills or args.urls):
        parser.error("give at least one --query, --skill or --url")
    if getattr(args, "append", False) and format_for(args.output, args.format) == "json":
        parser.error("--append needs -o with a .jsonl or .csv file (or --format jsonl/csv)")

    def on_retry(attempt: int, delay: float, exc: BaseException) -> None:
        _log(args, f"  retry {attempt} in {delay:.0f}s ({type(exc).__name__})")

    if scraper is None:
        scraper = UpworkScraper(
            proxy_country=args.country,
            retries=args.retries,
            workers=args.workers,
            on_retry=on_retry,
        )

    try:
        if args.command == "job":
            jobs: list[Job] = []
            failed = 0
            for ref in args.jobs:
                try:
                    jobs.append(scraper.job(ref))
                except (JobNotFoundError, LoginRequiredError) as exc:
                    failed += 1
                    print(f"error: {exc}", file=sys.stderr)
            if jobs:
                _emit(args, jobs)
            return 2 if failed else 0

        if args.command == "skill" and args.related:
            return _run_related(args, scraper)

        if args.command == "watch":
            return _run_watch(args, scraper)

        if args.command == "search":
            queries = args.queries or ([] if args.urls else [""])
            what = ", ".join(q or "(all jobs)" for q in queries + args.urls)
            _log(args, f"Searching Upwork jobs: {what}")
            jobs = scraper.collect(
                queries=queries,
                urls=args.urls,
                limit=args.limit,
                details=args.details,
                job_filter=_job_filter(args),
                max_pages=args.max_pages,
                on_page=_on_page(args),
                on_error=_on_error(args),
                **_search_options(args),
            )
        else:
            _log(args, f"Reading Upwork skill feeds: {', '.join(args.skills)}")
            jobs = scraper.collect(
                skills=args.skills,
                limit=args.limit or 1000,
                details=args.details,
                job_filter=_job_filter(args),
                on_page=_on_page(args),
                on_error=_on_error(args),
            )
    except (LoginRequiredError, SkillNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (UpworkError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _emit(args, jobs)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
