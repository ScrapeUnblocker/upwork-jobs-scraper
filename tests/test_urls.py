from __future__ import annotations

import pytest
from conftest import url_params

from upwork_jobs_scraper.urls import SearchQuery, job_id_from, job_url, skill_slug, skill_url


def test_default_query_url():
    assert SearchQuery("web scraping").to_url() == (
        "https://www.upwork.com/nx/search/jobs/?q=web%20scraping"
    )
    assert SearchQuery().to_url() == "https://www.upwork.com/nx/search/jobs/"


def test_query_with_every_option():
    query = SearchQuery(
        "python",
        sort="newest",
        job_type="hourly",
        experience=("intermediate", "expert"),
        duration=("week", "ongoing"),
        client_hires=("none", "10+"),
        per_page=50,
        page=3,
        extra=(("category2_uid", "123"),),
    )
    url = query.to_url()
    assert "contractor_tier=2,3" in url and "client_hires=0,10-" in url
    params = url_params(url)
    assert params == {
        "q": ["python"],
        "sort": ["recency"],
        "t": ["0"],
        "contractor_tier": ["2,3"],
        "duration_v3": ["week,ongoing"],
        "client_hires": ["0,10-"],
        "per_page": ["50"],
        "page": ["3"],
        "category2_uid": ["123"],
    }


def test_round_trip_from_url():
    query = SearchQuery(
        "data entry",
        sort="newest",
        job_type="fixed",
        experience=("entry",),
        duration=("month",),
        client_hires=("1-9",),
        per_page=20,
        page=2,
    )
    assert SearchQuery.from_url(query.to_url()) == query


def test_from_url_keeps_unknown_params_and_drops_tracking():
    query = SearchQuery.from_url(
        "https://www.upwork.com/nx/search/jobs/?q=logo&nbs=1&sort=relevance%2Bdesc&location=Americas"
    )
    assert query.query == "logo" and query.sort == "relevance"
    assert query.extra == (("location", "Americas"),)


def test_with_page():
    assert SearchQuery("x").with_page(4).page == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sort": "cheapest"},
        {"job_type": "weekly"},
        {"experience": ("guru",)},
        {"duration": ("decade",)},
        {"client_hires": ("5",)},
        {"per_page": 100},
        {"page": 0},
    ],
)
def test_invalid_query_options(kwargs):
    with pytest.raises(ValueError):
        SearchQuery("x", **kwargs)


@pytest.mark.parametrize(
    "url",
    ["https://www.example.com/nx/search/jobs/?q=x", "https://www.upwork.com/freelance-jobs/x/"],
)
def test_from_url_rejects_other_pages(url):
    with pytest.raises(ValueError):
        SearchQuery.from_url(url)


@pytest.mark.parametrize(
    "value",
    [
        "~022097119470235197340",
        "2097119470235197340",
        "https://www.upwork.com/jobs/~022097119470235197340",
        "https://www.upwork.com/freelance-jobs/apply/Python-Developer_~022097119470235197340/",
    ],
)
def test_job_id_from(value):
    assert job_id_from(value) == "~022097119470235197340"
    assert job_url(value) == "https://www.upwork.com/jobs/~022097119470235197340"


@pytest.mark.parametrize("value", ["", "python", "~0", "https://www.upwork.com/jobs/"])
def test_job_id_from_rejects(value):
    with pytest.raises(ValueError):
        job_id_from(value)


@pytest.mark.parametrize(
    "value, slug",
    [
        ("web-scraping", "web-scraping"),
        ("Web Scraping", "web-scraping"),
        ("https://www.upwork.com/freelance-jobs/data-entry/", "data-entry"),
        ("  Python ", "python"),
    ],
)
def test_skill_slug(value, slug):
    assert skill_slug(value) == slug
    assert skill_url(value) == f"https://www.upwork.com/freelance-jobs/{slug}/"


@pytest.mark.parametrize("value", ["", "  ", "!!!", "https://www.upwork.com/freelance-jobs/apply/"])
def test_skill_slug_rejects(value):
    with pytest.raises(ValueError):
        skill_slug(value)
