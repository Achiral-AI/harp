"""In-process counters for `/ai/multi-agent` outcomes.

Exposed via the ``GET /stats`` HTTP endpoint and consumed by the ``make watch``
dashboard. Counters are reset whenever the Harp container restarts; that's
fine for a single-user localhost tool.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass
class _Snapshot:
    started_at: float
    uptime_s: float
    total: int
    served_local: int
    forwarded_upstream: int
    rejected_local_only: int
    errors: int
    local_serve_ratio: float
    ineligibility_reasons: dict[str, int]
    forward_reasons: dict[str, int]

    def to_dict(self) -> dict:
        return self.__dict__


class StatsRegistry:
    """Tracks how many `/ai/multi-agent` calls were served local vs forwarded."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = time()
        self._total = 0
        self._served_local = 0
        self._forwarded_upstream = 0
        self._rejected_local_only = 0
        self._errors = 0
        self._ineligibility_reasons: Counter[str] = Counter()
        self._forward_reasons: Counter[str] = Counter()

    # --- recorders -----------------------------------------------------------

    def record_served_local(self) -> None:
        with self._lock:
            self._total += 1
            self._served_local += 1

    def record_forwarded_upstream(self, *, reason: str) -> None:
        with self._lock:
            self._total += 1
            self._forwarded_upstream += 1
            self._forward_reasons[reason] += 1

    def record_rejected_local_only(self, *, reason: str) -> None:
        with self._lock:
            self._total += 1
            self._rejected_local_only += 1
            self._ineligibility_reasons[reason] += 1

    def record_ineligibility(self, *, reason: str) -> None:
        """Track *why* a request wasn't served locally, even when forwarded."""
        with self._lock:
            self._ineligibility_reasons[reason] += 1

    def record_error(self) -> None:
        with self._lock:
            self._errors += 1

    def record_local_error(self, *, reason: str) -> None:
        with self._lock:
            self._total += 1
            self._errors += 1
            self._ineligibility_reasons[reason] += 1

    # --- accessors -----------------------------------------------------------

    def snapshot(self) -> _Snapshot:
        with self._lock:
            now = time()
            ratio = (self._served_local / self._total) if self._total else 0.0
            return _Snapshot(
                started_at=self._started_at,
                uptime_s=now - self._started_at,
                total=self._total,
                served_local=self._served_local,
                forwarded_upstream=self._forwarded_upstream,
                rejected_local_only=self._rejected_local_only,
                errors=self._errors,
                local_serve_ratio=ratio,
                ineligibility_reasons=dict(self._ineligibility_reasons),
                forward_reasons=dict(self._forward_reasons),
            )
