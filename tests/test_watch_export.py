from __future__ import annotations

import csv
import json

import pytest

from upwork_jobs_scraper.export import format_for, render, to_csv, write
from upwork_jobs_scraper.models import Job
from upwork_jobs_scraper.watch import SeenJobs


def make_job(n: int, **kwargs) -> Job:
    return Job(
        job_id=f"~02{n:019d}",
        title=f"Job {n} - café menu",
        url=f"https://www.upwork.com/jobs/~02{n:019d}",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# SeenJobs
# --------------------------------------------------------------------------- #


def test_seen_jobs_round_trip(tmp_path):
    path = tmp_path / "state" / "seen.json"
    store = SeenJobs(path)
    assert store.is_new_store and len(store) == 0
    jobs = [make_job(1), make_job(2)]
    assert store.filter_new(jobs + [make_job(1)]) == jobs
    store.add(jobs)
    store.save()
    again = SeenJobs(path)
    assert not again.is_new_store and len(again) == 2
    assert make_job(1).job_id in again
    assert again.filter_new([make_job(2), make_job(3)]) == [make_job(3)]
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not (tmp_path / "state" / "seen.json.tmp").exists()


def test_seen_jobs_forgets_oldest(tmp_path):
    store = SeenJobs(tmp_path / "seen.json", max_size=3)
    store.add([make_job(n) for n in range(1, 6)])
    assert len(store) == 3
    assert make_job(1).job_id not in store and make_job(5).job_id in store
    store.add(["~02custom"])
    assert "~02custom" in store and make_job(3).job_id not in store


def test_seen_jobs_discard(tmp_path):
    store = SeenJobs(tmp_path / "seen.json")
    store.add([make_job(1), make_job(2)])
    store.discard([make_job(1), "~02unknown"])
    assert make_job(1).job_id not in store and make_job(2).job_id in store


def test_seen_jobs_rejects_foreign_files(tmp_path):
    path = tmp_path / "other.json"
    path.write_text('["not", "a", "state"]', encoding="utf-8")
    with pytest.raises(ValueError):
        SeenJobs(path)
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    assert SeenJobs(empty).is_new_store
    with pytest.raises(ValueError):
        SeenJobs(empty, max_size=0)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_csv_joins_lists_and_formats_booleans():
    text = to_csv([make_job(1, skills=["Python", "Scrapy"], details_fetched=True)])
    row = next(csv.DictReader(text.splitlines()))
    assert row["skills"] == "Python; Scrapy"
    assert row["details_fetched"] == "true"
    assert row["fixed_budget"] == ""


def test_format_for():
    assert format_for("jobs.CSV") == "csv"
    assert format_for("jobs.jsonl") == "jsonl"
    assert format_for("jobs.txt") == "json"
    assert format_for(None, "jsonl") == "jsonl"
    with pytest.raises(ValueError):
        format_for(None, "xml")


def test_render_json_and_jsonl():
    jobs = [make_job(1), make_job(2)]
    assert [j["job_id"] for j in json.loads(render(jobs, "json"))] == [
        jobs[0].job_id,
        jobs[1].job_id,
    ]
    lines = render(jobs, "jsonl").splitlines()
    assert len(lines) == 2 and "café" in lines[0]


def test_write_csv_with_bom_and_append(tmp_path):
    path = tmp_path / "jobs.csv"
    write([make_job(1)], path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    write([make_job(2)], path, append=True)
    rows = list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    assert [r["job_id"] for r in rows] == [make_job(1).job_id, make_job(2).job_id]


def test_write_jsonl_append_and_json_refuses(tmp_path):
    path = tmp_path / "jobs.jsonl"
    write([make_job(1)], path, append=True)  # new file
    write([make_job(2)], path, append=True)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    with pytest.raises(ValueError):
        write([make_job(1)], tmp_path / "jobs.json", append=True)
