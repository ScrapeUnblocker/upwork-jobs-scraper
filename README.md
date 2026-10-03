# Upwork Jobs Scraper

[![CI](https://github.com/ScrapeUnblocker/upwork-jobs-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/upwork-jobs-scraper/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-6f42c1.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

**Scrape [Upwork](https://www.upwork.com) freelance job postings into clean JSON or CSV, and get
alerts for new jobs.**
Search by keyword or follow a skill's job feed. For every job you get the title, full
description, fixed budget or hourly rate range, experience level, project length, workload,
skills, posting time and URL. Optionally you also get everything from the job's own page: proposals and
interviews so far, the client's country, city, time zone, payment verification, rating, reviews,
total spend, hires and member-since date, plus category and freelancer requirements.

Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos):
the `getPageSource` API loads each Upwork page in a real browser and returns the HTML. This
package decodes the data Upwork embeds in those pages into typed records. You don't need to
run proxies, headless browsers or retry logic yourself.

## Features

- **Three public data sources.**
  - **Job search**: any keywords (or none, for every job), sorted by relevance or newest, 10/20/50 per
    page with automatic paging.
  - **Skill job feeds** (`/freelance-jobs/<skill>/`): recent jobs for a skill such as
    `web-scraping`, `python` or `logo-design`, plus the skill's open-job count and related
    skills.
  - **Job pages**: full details for any public job by ID or URL.
- **Every filter a signed-out visitor can use.** Job type (hourly/fixed), experience level
  (entry/intermediate/expert), project length, and the client's hire history. You can also paste a
  search URL from your browser or pass raw URL parameters with `--param`.
- **Client-side filters for the rest.** Upwork asks signed-out visitors to log in before they
  can filter by budget, hourly rate, proposals or payment verification, so this package applies those filters
  itself: minimum fixed budget, minimum hourly rate, posted within N hours, excluded keywords,
  and, with job details, payment verified, maximum proposals, minimum client spend, minimum
  client rating and client country.
- **Job alerts.** `watch` remembers which jobs it has already reported (in a small JSON state
  file) and outputs only new ones. A job whose page can't be loaded is held back and retried on
  the next run. Run it from cron, Task Scheduler or a scheduled CI job.
  `examples/job_alerts.py` also posts the new jobs to a Slack or Discord webhook.
- **Clean, consistent records.** Search highlights and HTML entities are stripped, timestamps
  are normalised to UTC ISO 8601, country codes (`USA`, `CAN`) are mapped to names, and
  Upwork's different workload labels are unified.
- **Multi-query and multi-skill runs** de-duplicated by job ID. Job pages are fetched in
  parallel (`--workers`).
- **Resilient.** Timeouts, transient API errors and pages without Upwork data are retried with
  doubling backoff. Login walls, unknown skills and closed jobs raise clear errors.
- **JSON, JSON Lines or CSV**, with `--append` for growing a file across `watch` runs.
- **CLI + Python library.** Type-hinted, and tested offline with a mocked client.

## Install

```bash
git clone https://github.com/ScrapeUnblocker/upwork-jobs-scraper.git
cd upwork-jobs-scraper
pip install .
```

Get an API key at [scrapeunblocker.com](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
and expose it as `SCRAPEUNBLOCKER_KEY` (the official SDK reads it from there):

```bash
export SCRAPEUNBLOCKER_KEY=your_key_here        # Windows PowerShell: $env:SCRAPEUNBLOCKER_KEY="your_key_here"
```

Or copy `.env.example` to `.env` and load it with your tool of choice. Never commit a real key.

## CLI usage

```bash
# Newest 20 "web scraping" jobs (JSON to stdout)
upwork-jobs-scraper search "web scraping" --sort newest --limit 20

# Expert-level hourly Python and Django jobs, to CSV
upwork-jobs-scraper search "python" "django" --type hourly --experience expert -o jobs.csv

# Every new fixed-price job of $1,000+ (no keywords = all jobs)
upwork-jobs-scraper search --sort newest --type fixed --min-fixed-budget 1000 --limit 100

# Short projects from clients who have hired before, with client details
upwork-jobs-scraper search "data entry" --duration week --client-hires 1-9,10+ --details

# Recent jobs from two skill feeds, only verified clients with < 15 proposals
upwork-jobs-scraper skill web-scraping data-scraping --payment-verified --max-proposals 15 -o feed.csv

# What's related to a skill, with open-job counts
upwork-jobs-scraper skill web-scraping --related

# Full details for specific jobs (ID, numeric uid or URL)
upwork-jobs-scraper job ~022105906533075902116 "https://www.upwork.com/jobs/~022105434304081048389"

# Job alerts: first record what's there, then only output new jobs on each run
upwork-jobs-scraper watch --skill web-scraping --query "scrapy" --state seen.json --baseline
upwork-jobs-scraper watch --skill web-scraping --query "scrapy" --state seen.json \
    --min-hourly-rate 40 --payment-verified -o new_jobs.jsonl --append
```

`python -m upwork_jobs_scraper ...` works too. Progress goes to stderr, so stdout stays clean
for piping. Add `-q` to silence it.

| Option | Meaning |
| --- | --- |
| `search QUERY...` / `--url` | Keywords (several = several searches, de-duplicated), or an Upwork job search URL |
| `skill SKILL...` | Skill feed slugs, names or URLs, e.g. `web-scraping`, `"Logo Design"` |
| `job JOB...` | Job IDs (`~02...`), numeric uids or job URLs |
| `watch --query/--skill/--url --state FILE` | Output only jobs not seen on earlier runs; `--baseline` records without output |
| `--sort` | `relevance` (default) or `newest` |
| `--type` | `hourly` or `fixed` |
| `--experience` | `entry`, `intermediate`, `expert` (comma-separated) |
| `--duration` | `week` (<1 month), `month` (1-3), `semester` (3-6), `ongoing` (6+ months) |
| `--client-hires` | `none`, `1-9`, `10+` - the client's past hires |
| `--per-page`, `--max-pages`, `--param KEY=VALUE` | Paging control and raw URL parameters |
| `--limit` | Max jobs per query / skill (search and watch default 50; skill default: the whole feed) |
| `--details` | Fetch each job's page (one request per job) for client and activity fields |
| `--min-fixed-budget`, `--min-hourly-rate` | Drop fixed jobs under a budget / hourly jobs whose posted top rate is lower |
| `--posted-within HOURS`, `--exclude WORDS` | Recency and keyword exclusion |
| `--payment-verified`, `--max-proposals`, `--min-client-spent`, `--min-client-rating`, `--client-country` | Client-level filters (fetch job pages automatically) |
| `-o`, `--format`, `--append` | Output file (`.json`, `.jsonl`, `.csv`), explicit format, append mode |
| `--country`, `--retries`, `--workers` | Request routing country (default `US`), retries per request, parallel job pages |

### What signed-out Upwork shows

This scraper reads the public pages anyone can open without an Upwork account. A few things are
good to know:

- **Signed-out search is a subset.** Upwork shows signed-out visitors fewer search results than
  logged-in freelancers see. In our testing the results were postings open to US-based
  freelancers. For a wider view of a skill, add its skill feed (`skill` / `--skill`): it lists
  recent postings from clients worldwide and reports the skill's total open-job count.
- **Some filters need a login.** Upwork redirects signed-out visitors to its login page when a
  search uses budget, hourly rate, proposals or payment-verified filters, or sorts by client spend or rating.
  The scraper raises `LoginRequiredError` and exits with code 2 in that case. Use the
  client-side filters above instead.
- **Skill feeds are a single page** of recent jobs (Upwork ignores paging there). For more
  jobs, combine several related skills; `--related` lists them.
- **Client and activity fields come from the job page.** Search results and feeds don't
  include them, so they are `null` unless you pass `--details` or use a client-level filter.

## Library usage

```python
from upwork_jobs_scraper import UpworkScraper

scraper = UpworkScraper()  # reads SCRAPEUNBLOCKER_KEY; or UpworkScraper(api_key="...")

jobs = scraper.search("web scraping", sort="newest", job_type="fixed", limit=30)
for job in jobs:
    print(job.posted_at, job.fixed_budget, job.experience_level, job.title, job.url)

# Full details for one job
job = scraper.job("~022105906533075902116")
print(job.proposals, job.client_country, job.client_total_spent, job.client_payment_verified)
```

Combining sources, filters and details:

```python
from upwork_jobs_scraper import JobFilter, SeenJobs, UpworkScraper
from upwork_jobs_scraper.export import write

scraper = UpworkScraper(workers=4, on_retry=lambda n, delay, exc: print("retry", n, exc))

# Search + skill feeds, de-duplicated; job pages fetched because of the client filters
jobs = scraper.collect(
    queries=["scrapy", "playwright"],
    skills=["web-scraping", "data-scraping"],
    sort="newest",
    limit=25,  # per query / skill
    job_filter=JobFilter(min_hourly_rate=35, payment_verified=True, max_proposals=20),
)
write(jobs, "upwork_jobs.csv")

# One skill feed: open-job count and related skills
feed = scraper.skill("Web Scraping")
print(feed.total_jobs, [(r.slug, r.open_jobs) for r in feed.related_skills])

# New-job detection between runs
store = SeenJobs("seen.json")
new = store.filter_new(jobs)
store.add(jobs)
store.save()
```

Lower-level building blocks: `make_query(...)` / `SearchQuery` (build and parse search URLs),
`scraper.fetch_search_page(query)` (one page with `total`), `scraper.enrich(jobs)`, and the
offline parsers `parse_search_page`, `parse_skill_page`, `parse_job_page`.

Errors: `LoginRequiredError` (filter needs an Upwork account), `JobNotFoundError` (unknown,
closed or private job), `SkillNotFoundError` (no feed for that slug), `UpworkParseError` (no
Upwork data after all retries). The SDK's own exceptions (bad key, out of credit, ...) pass
through unchanged.

## Example output

`upwork-jobs-scraper search "web scraping" --sort newest --limit 3 --details` (real output, the
second record, with the description shortened here):

```text
Searching Upwork jobs: web scraping
  search 'web scraping' page 1: 10 jobs (17 total)
3 jobs
```

```json
{
  "job_id": "~022105906533075902116",
  "title": "Data Mining: Active CDL Fleet Companies (Florida & SE US) - Email Campaign Ready",
  "url": "https://www.upwork.com/jobs/~022105906533075902116",
  "uid": "2105906533075902116",
  "source": "search",
  "query": "web scraping",
  "description": "Description:\nI need an experienced data miner to extract an exhaustive list of active commercial CDL fleet companies starting with Florida ...",
  "job_type": "fixed",
  "fixed_budget": 150.0,
  "hourly_min": null,
  "hourly_max": null,
  "currency": "USD",
  "experience_level": "Intermediate",
  "duration": "3 to 6 months",
  "duration_weeks": 18,
  "workload": null,
  "skills": ["Data Mining", "Data Scraping", "Email Communication", "Email Campaign Setup"],
  "category": "Data Mining & Management",
  "category_group": "Data Science & Analytics",
  "occupation": "Data Mining",
  "posted_at": "2026-10-02T06:28:38Z",
  "renewed_at": null,
  "positions": 1,
  "contract_to_hire": false,
  "proposals": 10,
  "interviewing": 0,
  "invites_sent": 0,
  "unanswered_invites": 0,
  "hired": 0,
  "client_last_active_at": "2026-10-02T13:12:20Z",
  "preferred_countries": ["United States"],
  "min_job_success_score": null,
  "client_country": "United States",
  "client_city": null,
  "client_timezone": "America/Chicago (UTC-05:00)",
  "client_payment_verified": true,
  "client_rating": null,
  "client_reviews": 0,
  "client_total_spent": 0.0,
  "client_hires": 0,
  "client_active_hires": 0,
  "client_member_since": "2026-10-02",
  "client_industry": null,
  "client_enterprise": false,
  "details_fetched": true
}
```

Jobs are live, so you'll see different postings.

### Field notes

- `job_id` is Upwork's job ciphertext (`~02...`); `url` is the canonical job page. `uid` is the
  numeric ID that the job commands also accept.
- `fixed_budget` is set for fixed-price jobs. `hourly_min`/`hourly_max` are set for hourly jobs
  when the client posted a rate. Skill feeds only carry the top of the range (`hourly_max`), and
  job details fill in the rest. Amounts are in `currency` (Upwork posts budgets in USD).
- `experience_level` is `Entry level`, `Intermediate` or `Expert`. `workload` is
  `Less than 30 hrs/week` or `More than 30 hrs/week` for hourly jobs.
- `posted_at` is when the job was published; `renewed_at` is when the client re-posted it
  (from search results and skill feeds). Both are UTC.
- `proposals`, `interviewing`, `invites_sent`, `hired` and `client_last_active_at` are the
  activity figures from the job page at the time of scraping.
- `client_rating` (0-5) is `null` until the client has a review. `client_total_spent` is in
  USD and is `0.0` for clients who haven't spent anything yet. `client_hires` counts the
  client's past contracts, and `client_active_hires` the ones still running.
- `preferred_countries` and `min_job_success_score` are the freelancer requirements the client set.
- `source` is `search`, `skill` or `job`, and `query` is the search keywords or skill slug
  that found the job.

## Project layout

```text
upwork-jobs-scraper/
├── src/upwork_jobs_scraper/
│   ├── __init__.py      # public API + __version__
│   ├── scraper.py       # UpworkScraper: fetching, retries, paging, details, de-duplication
│   ├── parsing.py       # page data -> Job / SearchPage / SkillPage, error detection
│   ├── nuxt.py          # decoder for the __NUXT_DATA__ payload Upwork embeds
│   ├── urls.py          # SearchQuery, job/skill URL helpers
│   ├── filters.py       # JobFilter: client-side listing and client filters
│   ├── watch.py         # SeenJobs: new-job detection between runs
│   ├── models.py        # dataclasses
│   ├── export.py        # JSON / JSON Lines / CSV writers
│   ├── cli.py           # `upwork-jobs-scraper` command
│   └── __main__.py      # `python -m upwork_jobs_scraper`
├── examples/
│   ├── search_to_json.py      # newest jobs for a search -> JSON file
│   ├── skill_feeds_to_csv.py  # several skill feeds + client details -> CSV
│   └── job_alerts.py          # new jobs since last run, optional Slack/Discord webhook
├── tests/                     # offline tests with a fake client + synthetic pages
├── pyproject.toml
├── requirements.txt
├── Makefile
└── .github/workflows/ci.yml
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
make install      # pip install -e ".[dev]"
make lint         # ruff check
make format       # ruff format
make test         # pytest (offline, no API key needed)
pre-commit install
```

The tests build small synthetic pages in Upwork's embedded-data format and replay them through
a fake client. They spend no API credit and run in CI on Python 3.9 and 3.12.

## Responsible use

This project reads only public pages that anyone can open without an account. Scrape at a
reasonable pace and respect Upwork's terms of use. Job and client details change constantly,
so treat results as a snapshot. This project is not affiliated with or endorsed by Upwork.

## Links

- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) - the web scraping API behind this project
- [ScrapeUnblocker documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) - `getPageSource`, SDKs, parsing options
- [Python SDK on PyPI](https://pypi.org/project/scrapeunblocker/) - `pip install scrapeunblocker`

## License

[MIT](LICENSE) - Copyright (c) 2026 ScrapeUnblocker
