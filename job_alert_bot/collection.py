"""One in-process collection point shared by every Discord server."""

import asyncio
import time
from dataclasses import dataclass

from .jobs import JobListing, canonical_url_hash, ranked_jobs
from .source_errors import SourceFailure, TemporarySourceFailure
from .sources import JobSource


@dataclass(frozen=True)
class EnabledSource:
    name: str
    adapter: JobSource
    # Zero means no result retention beyond concurrent requests.
    permitted_cache_seconds: int = 0


@dataclass(frozen=True)
class SourceStatus:
    kind: str
    detail: str
    cached: bool = False
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class CollectionResult:
    jobs: list[JobListing]
    statuses: dict[str, SourceStatus]

    @property
    def all_unavailable(self) -> bool:
        return not any(status.kind in {"success", "no_results"} for status in self.statuses.values())

    @property
    def partial_failure(self) -> bool:
        return not self.all_unavailable and any(status.kind in
            {"quota_exhausted", "authentication_failed", "temporary_error", "unavailable", "disabled"}
            for status in self.statuses.values())


@dataclass
class _SourceState:
    cached_jobs: list[JobListing] | None = None
    cache_until: float = 0
    retry_at: float = 0
    last_error: SourceStatus | None = None


class CollectionService:
    def __init__(self, enabled: list[EnabledSource], disabled: dict[str, str] | None = None):
        self.enabled = enabled
        self.disabled = disabled or {}
        self._states: dict[str, _SourceState] = {source.name: _SourceState() for source in enabled}
        self._lock = asyncio.Lock()
        self._last_report: CollectionResult | None = None
        self._generation = 0

    def cached_report(self) -> CollectionResult:
        """Return only results still inside each provider's permitted retention."""
        jobs: list[JobListing] = []
        statuses = {name: SourceStatus("disabled", reason) for name, reason in self.disabled.items()}
        now = time.monotonic()
        for source in self.enabled:
            state = self._states[source.name]
            if state.cached_jobs is not None and now < state.cache_until:
                jobs.extend(state.cached_jobs)
                statuses[source.name] = SourceStatus(
                    "success" if state.cached_jobs else "no_results", "Permitted cache", cached=True)
            elif state.last_error is not None:
                statuses[source.name] = state.last_error
            else:
                statuses[source.name] = SourceStatus("unavailable", "No retained results; next collection is 6 PM Philippine time")
        unique = []
        seen_ids, seen_urls = set(), set()
        for job in ranked_jobs(jobs):
            url_hash = canonical_url_hash(job.application_url)
            if job.key in seen_ids or (url_hash and url_hash in seen_urls):
                continue
            unique.append(job)
            seen_ids.add(job.key)
            if url_hash:
                seen_urls.add(url_hash)
        return CollectionResult(unique, statuses)

    async def collect(self) -> CollectionResult:
        observed_generation = self._generation
        async with self._lock:
            # Concurrent guild commands share the collection that just completed.
            if self._last_report is not None and self._generation != observed_generation:
                return self._last_report
            jobs: list[JobListing] = []
            statuses = {name: SourceStatus("disabled", reason)
                        for name, reason in self.disabled.items()}
            for source in self.enabled:
                state = self._states[source.name]
                now = time.monotonic()
                if state.cached_jobs is not None and now < state.cache_until:
                    jobs.extend(state.cached_jobs)
                    statuses[source.name] = SourceStatus(
                        "success" if state.cached_jobs else "no_results", "Reused permitted cached search",
                        cached=True)
                    continue
                state.cached_jobs = None  # discard data when the allowed retention ends
                if now < state.retry_at and state.last_error is not None:
                    remaining = None if state.retry_at == float("inf") else max(1, int(state.retry_at - now))
                    statuses[source.name] = SourceStatus(state.last_error.kind, state.last_error.detail,
                                                         retry_after_seconds=remaining)
                    continue
                try:
                    found = await source.adapter.fetch_jobs()
                    if not isinstance(found, list):
                        raise SourceFailure("Provider returned an invalid job batch")
                except SourceFailure as exc:
                    pause = (exc.retry_after_seconds if isinstance(exc, TemporarySourceFailure)
                             and exc.retry_after_seconds is not None else 60)
                    state.retry_at = (float("inf") if exc.kind in
                                      {"quota_exhausted", "authentication_failed"} else time.monotonic() + pause)
                    state.last_error = SourceStatus(exc.kind, str(exc))
                    statuses[source.name] = state.last_error
                    continue
                except Exception:
                    state.retry_at = time.monotonic() + 60
                    state.last_error = SourceStatus("temporary_error", "Unexpected provider error")
                    statuses[source.name] = state.last_error
                    continue
                state.last_error = None
                state.retry_at = 0
                statuses[source.name] = SourceStatus("success" if found else "no_results",
                                                     "Search completed" if found else "Search returned no results")
                jobs.extend(found)
                if source.permitted_cache_seconds > 0:
                    state.cached_jobs = found
                    state.cache_until = time.monotonic() + source.permitted_cache_seconds
            # Rank first; when the same stable ID or canonical URL appears twice,
            # retain the listing with the stronger comparable base salary.
            unique: list[JobListing] = []
            seen_ids: set[str] = set()
            seen_urls: set[str] = set()
            for job in ranked_jobs(jobs):
                url_hash = canonical_url_hash(job.application_url)
                if job.key in seen_ids or (url_hash and url_hash in seen_urls):
                    continue
                unique.append(job)
                seen_ids.add(job.key)
                if url_hash:
                    seen_urls.add(url_hash)
            report = CollectionResult(unique, statuses)
            self._last_report = report
            self._generation += 1
            return report
