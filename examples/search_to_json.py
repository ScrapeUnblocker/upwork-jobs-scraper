"""Save the newest Upwork jobs for a search as JSON.

export SCRAPEUNBLOCKER_KEY=your_key_here
python examples/search_to_json.py "web scraping"
"""

from __future__ import annotations

import json
import sys

from upwork_jobs_scraper import UpworkScraper


def budget(job) -> str:
    if job.fixed_budget:
        return f"${job.fixed_budget:,.0f} fixed"
    if job.hourly_min or job.hourly_max:
        low = f"${job.hourly_min:,.0f}" if job.hourly_min else ""
        return f"{low}-${job.hourly_max:,.0f}/hr" if job.hourly_max else f"{low}/hr"
    return job.job_type or "-"


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "web scraping"

    scraper = UpworkScraper()  # reads SCRAPEUNBLOCKER_KEY
    jobs = scraper.search(query, sort="newest", limit=20)

    with open("upwork_jobs.json", "w", encoding="utf-8") as fh:
        json.dump([job.to_dict() for job in jobs], fh, indent=2, ensure_ascii=False)

    for job in jobs[:10]:
        print(f"{job.posted_at}  {budget(job):<18} {job.title[:70]}")
    print(f"Saved {len(jobs)} jobs to upwork_jobs.json")


if __name__ == "__main__":
    main()
