"""Decode the ``__NUXT_DATA__`` payload Upwork embeds in its server-rendered pages.

Upwork's pages are built with Nuxt, which serialises the page state with
`devalue <https://github.com/Rich-Harris/devalue>`_: one flat JSON array in
which objects and arrays hold *indexes* into that same array instead of
values, so repeated values are stored only once. :func:`decode` rebuilds the
plain Python structure (dicts, lists, strings, numbers).
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*\bid=[\"']__NUXT_DATA__[\"'][^>]*>(.*?)</script>", re.S | re.I
)

# devalue encodes these values as negative "indexes".
_SPECIAL: dict[int, Any] = {
    -1: None,  # undefined
    -2: None,  # array hole
    -3: math.nan,
    -4: math.inf,
    -5: -math.inf,
    -6: -0.0,
}

# Vue/Nuxt reactivity wrappers around a single value.
_WRAPPERS = frozenset({"Reactive", "ShallowReactive", "Ref", "ShallowRef", "NuxtError", "Island"})


class NuxtDataError(ValueError):
    """The page has no ``__NUXT_DATA__`` payload, or it is not valid devalue JSON."""


def find_payload(html: str) -> str | None:
    """Return the raw JSON text of the ``__NUXT_DATA__`` script, if the page has one."""
    match = _SCRIPT_RE.search(html or "")
    return match.group(1) if match else None


def decode(payload: str | list[Any]) -> Any:
    """Turn a devalue payload (JSON text or the parsed array) into plain Python data."""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError as exc:
        raise NuxtDataError(f"payload is not valid JSON: {exc}") from None
    if not isinstance(data, list) or not data:
        raise NuxtDataError("payload is not a devalue array")

    cache: dict[int, Any] = {}
    in_progress: set[int] = set()

    def hydrate(index: Any) -> Any:
        if not isinstance(index, int) or isinstance(index, bool):
            raise NuxtDataError(f"invalid reference {index!r}")
        if index < 0:
            return _SPECIAL.get(index)
        if index in cache:
            return cache[index]
        if index >= len(data):
            raise NuxtDataError(f"reference {index} is out of range")
        value = data[index]
        if isinstance(value, dict):
            obj: dict[str, Any] = {}
            cache[index] = obj
            for key, ref in value.items():
                obj[key] = hydrate(ref)
            return obj
        if isinstance(value, list):
            if value and isinstance(value[0], str):
                if index in in_progress:  # a wrapper that (indirectly) contains itself
                    return None
                in_progress.add(index)
                try:
                    result = typed(value[0], value[1:])
                finally:
                    in_progress.discard(index)
                cache[index] = result
                return result
            items: list[Any] = []
            cache[index] = items
            for ref in value:
                items.append(hydrate(ref))
            return items
        cache[index] = value
        return value

    def typed(tag: str, args: list[Any]) -> Any:
        if tag in _WRAPPERS:
            return hydrate(args[0]) if args else None
        if tag in ("EmptyRef", "EmptyShallowRef"):
            return None
        if tag in ("Date", "RegExp", "URL", "Object"):
            # Stored inline: an ISO date string, a regex source, a URL, a boxed primitive.
            return args[0] if args else None
        if tag == "BigInt":
            return int(args[0])
        if tag == "Set":
            return [hydrate(ref) for ref in args]
        if tag == "Map":
            return {str(hydrate(args[i])): hydrate(args[i + 1]) for i in range(0, len(args) - 1, 2)}
        if tag == "null":  # object without a prototype: inline keys, referenced values
            return {str(args[i]): hydrate(args[i + 1]) for i in range(0, len(args) - 1, 2)}
        # Custom reducers registered by the app wrap exactly one value.
        if len(args) == 1 and isinstance(args[0], int) and not isinstance(args[0], bool):
            return hydrate(args[0])
        return None

    return hydrate(0)


def extract(html: str) -> Any:
    """Find and decode the ``__NUXT_DATA__`` payload of a page.

    Raises:
        NuxtDataError: the page carries no payload (e.g. a block or error page).
    """
    payload = find_payload(html)
    if payload is None:
        raise NuxtDataError("page has no __NUXT_DATA__ payload")
    return decode(payload)
