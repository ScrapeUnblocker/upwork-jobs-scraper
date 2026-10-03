"""Remember which jobs were already reported, so repeated runs only surface new ones."""

from __future__ import annotations

import datetime as _dt
import json
import os
from collections.abc import Iterable
from pathlib import Path

from .models import Job


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SeenJobs:
    """A small JSON file of job ids already seen, oldest first.

    Args:
        path: Where the state lives, e.g. ``seen_jobs.json``. Created on first save.
        max_size: How many ids to keep; the oldest are forgotten first. Upwork
            jobs rarely stay open for long, so a few thousand is plenty.

    Example::

        store = SeenJobs("seen_jobs.json")
        new = store.filter_new(jobs)
        store.add(jobs)
        store.save()
    """

    def __init__(self, path: str | Path, *, max_size: int = 5000) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.path = Path(path)
        self.max_size = max_size
        self._seen: dict[str, str] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return
        data = json.loads(text)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict):
            raise ValueError(f"{self.path} is not a seen-jobs state file")
        self._seen = {str(k): str(v) for k, v in jobs.items()}

    def __contains__(self, job_id: object) -> bool:
        return job_id in self._seen

    def __len__(self) -> int:
        return len(self._seen)

    @property
    def is_new_store(self) -> bool:
        """True when nothing has been recorded yet (first run)."""
        return not self._seen

    def filter_new(self, jobs: Iterable[Job]) -> list[Job]:
        """The jobs whose id has not been seen before (order kept, duplicates dropped)."""
        out: list[Job] = []
        batch: set[str] = set()
        for job in jobs:
            if job.job_id in self._seen or job.job_id in batch:
                continue
            batch.add(job.job_id)
            out.append(job)
        return out

    def add(self, jobs: Iterable[Job | str]) -> None:
        stamp = _stamp()
        for job in jobs:
            job_id = job if isinstance(job, str) else job.job_id
            self._seen.setdefault(job_id, stamp)
        overflow = len(self._seen) - self.max_size
        if overflow > 0:
            for job_id in list(self._seen)[:overflow]:
                del self._seen[job_id]

    def discard(self, jobs: Iterable[Job | str]) -> None:
        """Forget jobs again, e.g. ones whose details could not be fetched this run."""
        for job in jobs:
            self._seen.pop(job if isinstance(job, str) else job.job_id, None)

    def save(self) -> Path:
        """Write the state atomically (a crash never leaves a half-written file)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps({"version": 1, "jobs": self._seen}, indent=0) + "\n", encoding="utf-8"
        )
        os.replace(tmp, self.path)
        return self.path
