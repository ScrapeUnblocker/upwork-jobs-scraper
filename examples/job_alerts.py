"""Simple Upwork job alerts: print (and optionally post) jobs you have not seen yet.

Run it on a schedule (cron, Task Scheduler, a CI cron job). The first run only
records the current jobs; later runs report what is new since the last run.
Set WEBHOOK_URL to a Slack or Discord incoming-webhook URL to get a message.

export SCRAPEUNBLOCKER_KEY=your_key_here
export WEBHOOK_URL=https://hooks.slack.com/services/...   # optional
python examples/job_alerts.py
"""

from __future__ import annotations

import json
import os
import urllib.request

from upwork_jobs_scraper import JobFilter, SeenJobs, UpworkScraper

QUERIES = ["web scraping", "scrapy"]
SKILLS = ["data-scraping"]
FILTER = JobFilter(
    min_fixed_budget=150,
    min_hourly_rate=25,
    exclude_keywords=("unpaid", "test task"),
    payment_verified=True,  # needs each new job's page; only new jobs are fetched
    max_proposals=20,
)


def notify(lines: list[str]) -> None:
    url = os.environ.get("WEBHOOK_URL")
    if not url or not lines:
        return
    key = "content" if "discord.com" in url else "text"
    body = json.dumps({key: "\n".join(lines)[:1900]}).encode("utf-8")
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=30).close()


def main() -> None:
    store = SeenJobs("upwork_seen_jobs.json")
    first_run = store.is_new_store
    scraper = UpworkScraper()  # reads SCRAPEUNBLOCKER_KEY

    listing = scraper.collect(
        queries=QUERIES, skills=SKILLS, sort="newest", limit=30, job_filter=FILTER.listing_only()
    )
    new = store.filter_new(listing)
    store.add(listing)
    if first_run:
        store.save()
        print(f"First run: recorded {len(listing)} jobs. New jobs will be reported next time.")
        return

    failed = []
    enriched = scraper.enrich(new, on_error=lambda job, exc: failed.append(job))
    store.discard(failed)  # page could not be read: try again on the next run
    new = [job for job in enriched if job.details_fetched and FILTER.match_details(job)]
    store.save()
    lines = [
        f"{job.title} | {job.client_country or '?'} | {job.proposals} proposals | {job.url}"
        for job in new
    ]
    print("\n".join(lines) or "No new matching jobs.")
    notify(lines)


if __name__ == "__main__":
    main()
