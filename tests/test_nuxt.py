from __future__ import annotations

import json
import math

import pytest
from conftest import encode, nuxt_html

from upwork_jobs_scraper.nuxt import NuxtDataError, decode, extract, find_payload


def test_round_trips_plain_data():
    state = {"vuex": {"jobs": [{"id": 1, "tags": ["a", "b"], "ok": True, "none": None}]}}
    assert decode(encode(state)) == state


def test_shared_references_and_wrappers():
    payload = [
        ["ShallowReactive", 1],
        {"a": 2, "b": 2, "c": 4, "d": -1, "e": 5},
        ["Reactive", 3],
        {"name": 6},
        ["UsnFacet", 3],  # custom reducer wrapping one value
        ["EmptyRef"],
        "shared",
    ]
    data = decode(json.dumps(payload))
    assert data["a"] == {"name": "shared"}
    assert data["a"] is data["b"]  # the same object, stored once
    assert data["c"] == {"name": "shared"}
    assert data["d"] is None and data["e"] is None


def test_typed_values():
    payload = [
        {"when": 1, "tags": 2, "lookup": 3, "bare": 4, "big": 5, "boxed": 6, "nums": 7},
        ["Date", "2026-10-01T10:00:00.000Z"],
        ["Set", 8, 9],
        ["Map", 8, 9],
        ["null", "key", 9],
        ["BigInt", "12345678901234567890"],
        ["Object", "boxed"],
        [-3, -4, -5, -6],
        "x",
        10,
    ]
    data = decode(payload)
    assert data["when"] == "2026-10-01T10:00:00.000Z"
    assert data["tags"] == ["x", 10]
    assert data["lookup"] == {"x": 10}
    assert data["bare"] == {"key": 10}
    assert data["big"] == 12345678901234567890
    assert data["boxed"] == "boxed"
    nan, inf, ninf, nzero = data["nums"]
    assert math.isnan(nan) and inf == math.inf and ninf == -math.inf and nzero == 0


def test_cycles_do_not_recurse_forever():
    payload = [{"self": 0, "wrapped": 1}, ["Reactive", 1]]
    data = decode(payload)
    assert data["self"] is data
    assert data["wrapped"] is None


@pytest.mark.parametrize("payload", ["not json", "{}", "[]", '[{"a": 99}]', '[{"a": "x"}]'])
def test_invalid_payloads(payload):
    with pytest.raises(NuxtDataError):
        decode(payload)


def test_extract_from_html():
    html = nuxt_html({"path": "/x"})
    assert find_payload(html) is not None
    assert extract(html) == {"path": "/x"}


def test_extract_without_payload():
    assert find_payload("<html>blocked</html>") is None
    with pytest.raises(NuxtDataError):
        extract("<html>blocked</html>")
