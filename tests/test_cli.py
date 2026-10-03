from __future__ import annotations

import csv
import json

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
    url_params,
)

from upwork_jobs_scraper.cli import build_parser, main
from upwork_jobs_scraper.scraper import UpworkScraper


def fake_scraper(responder):
    client = FakeClient(responder)
    scraper = UpworkScraper(client=client, transient_errors=(), sleep=lambda _s: None, workers=1)
    return scraper, client


def site(url, _n):
    """Serves search pages, skill feeds and job pages by URL."""
    if "/nx/search/jobs/" in url:
        return search_html([search_job(1), fixed_search_job(2, budget=80)], total=2)
    if "/freelance-jobs/" in url:
        return skill_html([feed_job(2), feed_job(3)])
    return job_html(job_details(int(url[-4:])))


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def test_parser_search_options():
    args = build_parser().parse_args(
        [
            "search",
            "web scraping",
            "scrapy",
            "--sort",
            "newest",
            "--type",
            "fixed",
            "--experience",
            "intermediate,Expert",
            "--duration",
            "week,month",
            "--client-hires",
            "none,1-9",
            "--per-page",
            "50",
            "--param",
            "category2_uid=531770282580668420",
            "--limit",
            "80",
            "--min-fixed-budget",
            "250",
            "--exclude",
            "wordpress, unpaid",
            "--payment-verified",
            "--max-proposals",
            "15",
            "--client-country",
            "United States,Canada",
            "-o",
            "jobs.csv",
        ]
    )
    assert args.command == "search" and args.queries == ["web scraping", "scrapy"]
    assert args.sort == "newest" and args.job_type == "fixed"
    assert args.experience == ["intermediate", "expert"]
    assert args.duration == ["week", "month"] and args.client_hires == ["none", "1-9"]
    assert args.per_page == 50 and args.params == [("category2_uid", "531770282580668420")]
    assert args.limit == 80 and args.min_fixed_budget == 250
    assert args.exclude == ["wordpress", "unpaid"]
    assert args.payment_verified and args.max_proposals == 15
    assert args.client_countries == ["United States", "Canada"]
    assert args.country == "US" and args.workers == 3


@pytest.mark.parametrize(
    "argv",
    [
        ["search", "x", "--limit", "0"],
        ["search", "x", "--sort", "cheapest"],
        ["search", "x", "--experience", "guru"],
        ["search", "x", "--per-page", "100"],
        ["search", "x", "--param", "novalue"],
        ["search", "x", "--min-fixed-budget", "-5"],
        ["skill"],
        ["job"],
        ["watch"],
        ["search", "x", "--append"],
    ],
)
def test_parser_rejects_bad_input(argv, capsys):
    scraper, _ = fake_scraper(site)
    with pytest.raises(SystemExit) as exc:
        main(argv, scraper=scraper)
    assert exc.value.code == 2


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def test_search_to_stdout(capsys):
    scraper, client = fake_scraper(site)
    assert main(["search", "python", "--sort", "newest", "--limit", "5"], scraper=scraper) == 0
    jobs = json.loads(capsys.readouterr().out)
    assert [j["job_id"] for j in jobs] == [cipher(1), cipher(2)]
    assert url_params(client.calls[0][0])["sort"] == ["recency"]


def test_search_without_keywords_lists_all_jobs(capsys):
    scraper, client = fake_scraper(site)
    assert main(["search", "--sort", "newest", "--limit", "2", "-q"], scraper=scraper) == 0
    assert "q" not in url_params(client.calls[0][0])
    assert capsys.readouterr().err == ""


def test_search_with_client_filter_to_csv(tmp_path):
    out = tmp_path / "jobs.csv"
    scraper, client = fake_scraper(site)
    argv = ["search", "python", "--min-fixed-budget", "100", "--payment-verified", "-o", str(out)]
    assert main(argv, scraper=scraper) == 0
    rows = list(csv.DictReader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert [r["job_id"] for r in rows] == [cipher(1)]  # job 2 is a $80 fixed job
    assert rows[0]["details_fetched"] == "true" and rows[0]["client_country"] == "United States"
    assert len(client.calls) == 2  # search + one job page


def test_search_login_wall_exit_code(capsys):
    scraper, _ = fake_scraper(lambda url, n: LOGIN_HTML)
    assert main(["search", "python", "--param", "payment_verified=1"], scraper=scraper) == 2
    assert "log in" in capsys.readouterr().err


def test_skill_command_with_details(tmp_path):
    out = tmp_path / "feed.jsonl"
    scraper, client = fake_scraper(site)
    assert main(["skill", "web-scraping", "--details", "-o", str(out)], scraper=scraper) == 0
    jobs = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [j["job_id"] for j in jobs] == [cipher(2), cipher(3)]
    assert all(j["details_fetched"] and j["source"] == "skill" for j in jobs)
    assert len(client.calls) == 3


def test_skill_related_table(capsys):
    scraper, _ = fake_scraper(site)
    assert main(["skill", "Web Scraping", "--related"], scraper=scraper) == 0
    out = capsys.readouterr().out
    assert "Web Scraping (web-scraping): 317 open jobs" in out
    assert "data-scraping" in out and "3472" in out


def test_skill_related_json(capsys):
    scraper, _ = fake_scraper(site)
    assert main(["skill", "web-scraping", "--related", "--format", "json"], scraper=scraper) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["open_jobs"] == 317 and data[0]["related"][0]["slug"] == "data-scraping"


def test_unknown_skill_exit_code(capsys):
    scraper, _ = fake_scraper(lambda url, n: NotFound("404"))
    assert main(["skill", "nope-not-a-skill"], scraper=scraper) == 2
    assert "no job feed" in capsys.readouterr().err


def test_job_command_reports_missing_jobs(capsys):
    def responder(url, n):
        return NotFound("404") if url.endswith(cipher(9)) else site(url, n)

    scraper, _ = fake_scraper(responder)
    assert main(["job", cipher(4), cipher(9)], scraper=scraper) == 2
    captured = capsys.readouterr()
    jobs = json.loads(captured.out)
    assert [j["job_id"] for j in jobs] == [cipher(4)] and jobs[0]["proposals"] == 12
    assert "job not found" in captured.err


def test_watch_baseline_then_only_new_jobs(tmp_path, capsys):
    state = tmp_path / "seen.json"
    out = tmp_path / "new.jsonl"
    feeds = [[feed_job(1), feed_job(2)], [feed_job(1), feed_job(2), feed_job(3)]]

    def responder(url, n):
        if "/freelance-jobs/" in url:
            return skill_html(feeds.pop(0))
        return job_html(job_details(int(url[-4:])))

    scraper, client = fake_scraper(responder)
    base = ["watch", "--skill", "web-scraping", "--state", str(state)]
    assert main([*base, "--baseline"], scraper=scraper) == 0
    assert "recorded 2 jobs" in capsys.readouterr().err
    assert not out.exists()

    assert main([*base, "--details", "-o", str(out), "--append"], scraper=scraper) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["job_id"] for line in lines] == [cipher(3)]
    assert json.loads(lines[0])["details_fetched"] is True
    assert len(client.calls) == 3  # two feeds + one job page
    assert len(json.loads(state.read_text(encoding="utf-8"))["jobs"]) == 3


def test_watch_first_run_outputs_everything(tmp_path, capsys):
    scraper, _ = fake_scraper(site)
    argv = ["watch", "--query", "python", "--state", str(tmp_path / "s.json")]
    assert main(argv, scraper=scraper) == 0
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 2
    assert "First run" in captured.err
    assert main(argv, scraper=scraper) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_watch_retries_jobs_whose_details_failed(tmp_path, capsys):
    state = tmp_path / "seen.json"
    broken = {"on": True}

    def responder(url, n):
        if "/freelance-jobs/" in url:
            return skill_html([feed_job(1)])
        return NotFound("404") if broken["on"] else job_html(job_details(1))

    scraper, _ = fake_scraper(responder)
    argv = ["watch", "--skill", "web-scraping", "--state", str(state), "--details"]
    assert main(argv, scraper=scraper) == 0
    first = capsys.readouterr()
    assert json.loads(first.out) == [] and "no details for" in first.err
    assert json.loads(state.read_text(encoding="utf-8"))["jobs"] == {}

    broken["on"] = False
    assert main(argv, scraper=scraper) == 0
    second = json.loads(capsys.readouterr().out)
    assert [j["details_fetched"] for j in second] == [True]
    assert list(json.loads(state.read_text(encoding="utf-8"))["jobs"]) == [cipher(1)]
