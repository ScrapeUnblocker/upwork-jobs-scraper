"""Collect recent jobs from several skill feeds, add client details, and export a CSV.

Each job page is one extra request, so this example first drops fixed-price jobs
under $200 and hourly jobs whose posted rate tops out below $30/hr, then fetches
details for the rest.

export SCRAPEUNBLOCKER_KEY=your_key_here
python examples/skill_feeds_to_csv.py web-scraping data-scraping python
"""

from __future__ import annotations

import sys

from upwork_jobs_scraper import JobFilter, UpworkScraper
from upwork_jobs_scraper.export import write


def main() -> None:
    skills = sys.argv[1:] or ["web-scraping", "data-scraping"]

    scraper = UpworkScraper(workers=3)  # reads SCRAPEUNBLOCKER_KEY
    jobs = scraper.collect(
        skills=skills,
        limit=10,  # per skill
        details=True,
        job_filter=JobFilter(min_fixed_budget=200, min_hourly_rate=30),
    )

    # Clients who already spend on Upwork first.
    jobs.sort(key=lambda j: j.client_total_spent or 0, reverse=True)
    path = write(jobs, "upwork_skill_jobs.csv")

    for job in jobs[:10]:
        spent = f"${job.client_total_spent:,.0f}" if job.client_total_spent else "$0"
        verified = "verified" if job.client_payment_verified else "unverified"
        print(
            f"{spent:>10} spent | {job.client_country or '?':<15} | {verified:<10} | "
            f"{job.proposals if job.proposals is not None else '?':>3} proposals | {job.title[:50]}"
        )
    print(f"Saved {len(jobs)} jobs to {path}")


if __name__ == "__main__":
    main()
