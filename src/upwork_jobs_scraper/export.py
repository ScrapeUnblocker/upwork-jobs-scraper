"""Write scraped jobs to JSON, JSON Lines or CSV."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any

from .models import Job

CSV_FIELDS: list[str] = [f.name for f in fields(Job)]
FORMATS = ("json", "jsonl", "csv")


def _as_dict(item: Any) -> dict[str, Any]:
    return item.to_dict() if hasattr(item, "to_dict") else dict(item)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else value


def to_json(items: Iterable[Any], *, indent: int | None = 2) -> str:
    return json.dumps([_as_dict(i) for i in items], indent=indent, ensure_ascii=False)


def to_jsonl(items: Iterable[Any]) -> str:
    return "".join(json.dumps(_as_dict(i), ensure_ascii=False) + "\n" for i in items)


def to_csv(
    items: Iterable[Any], columns: Sequence[str] | None = None, *, header: bool = True
) -> str:
    """CSV text; list fields (skills, preferred countries) are joined with ``"; "``."""
    rows = [_as_dict(i) for i in items]
    columns = list(columns or (CSV_FIELDS if not rows or "job_id" in rows[0] else rows[0]))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    if header:
        writer.writeheader()
    for row in rows:
        writer.writerow({k: _csv_value(row.get(k)) for k in columns})
    return buf.getvalue()


def format_for(path: str | Path | None, explicit: str | None = None) -> str:
    """Pick an output format from an explicit choice or the file extension."""
    if explicit:
        if explicit not in FORMATS:
            raise ValueError(f"format must be one of {FORMATS}")
        return explicit
    suffix = Path(path).suffix.lower().lstrip(".") if path else ""
    return suffix if suffix in FORMATS else "json"


def render(items: Iterable[Any], fmt: str) -> str:
    if fmt == "csv":
        return to_csv(items)
    if fmt == "jsonl":
        return to_jsonl(items)
    return to_json(items) + "\n"


def write(
    items: Iterable[Any], path: str | Path, fmt: str | None = None, *, append: bool = False
) -> Path:
    """Write ``items`` to ``path`` (format from ``fmt`` or the extension).

    With ``append=True`` JSON Lines and CSV files are extended instead of
    replaced (a CSV header is only written to a new or empty file) - handy for
    collecting the output of repeated ``watch`` runs in one file.
    """
    path = Path(path)
    fmt = format_for(path, fmt)
    items = list(items)
    if append and fmt == "json":
        raise ValueError("append works with .jsonl and .csv output, not .json")
    exists = path.exists() and path.stat().st_size > 0
    if append and exists:
        text = to_csv(items, header=False) if fmt == "csv" else to_jsonl(items)
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path
    # utf-8-sig so Excel opens CSVs with non-English job titles correctly.
    encoding = "utf-8-sig" if fmt == "csv" else "utf-8"
    path.write_text(render(items, fmt), encoding=encoding, newline="")
    return path
