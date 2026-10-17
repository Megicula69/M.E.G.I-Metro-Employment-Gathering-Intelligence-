import asyncio
from decimal import Decimal

from job_alert_bot.collection import CollectionService, EnabledSource
from job_alert_bot import collection
from job_alert_bot.jobs import JobListing, Salary, SalaryPeriod
from job_alert_bot.source_errors import AuthenticationFailure, QuotaExhausted, TemporarySourceFailure


def listing(source, identifier, url, amount=50000):
    return JobListing(source, identifier, "Engineer", "Employer", "Makati City, NCR", True,
                      Salary(lower=Decimal(amount), period=SalaryPeriod.MONTHLY),
                      "Hybrid", "Full-time", url)


class Stub:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def fetch_jobs(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        await asyncio.sleep(0)
        return self.result


def test_quota_failure_keeps_other_source_and_no_repeated_quota_call():
    quota = Stub(QuotaExhausted("Lifetime quota exhausted"))
    other = Stub([listing("Other", "1", "https://example.org/job/1")])
    collector = CollectionService([EnabledSource("Quota", quota),
                                   EnabledSource("Other", other, permitted_cache_seconds=60)])
    first = asyncio.run(collector.collect())
    assert first.partial_failure and not first.all_unavailable
    assert first.statuses["Quota"].kind == "quota_exhausted"
    assert [job.source for job in first.jobs] == ["Other"]
    second = asyncio.run(collector.collect())
    assert quota.calls == 1 and other.calls == 1
    assert second.statuses["Other"].cached


def test_retry_after_authentication_and_no_results_are_distinct():
    temporary = Stub(TemporarySourceFailure("Rate limited", retry_after_seconds=120))
    auth = Stub(AuthenticationFailure("Bad key"))
    empty = Stub([])
    collector = CollectionService([EnabledSource("Temporary", temporary),
                                   EnabledSource("Auth", auth), EnabledSource("Empty", empty)])
    report = asyncio.run(collector.collect())
    assert report.statuses["Temporary"].kind == "temporary_error"
    assert report.statuses["Auth"].kind == "authentication_failed"
    assert report.statuses["Empty"].kind == "no_results"
    assert not report.all_unavailable and report.partial_failure
    again = asyncio.run(collector.collect())
    assert temporary.calls == auth.calls == 1
    assert again.statuses["Temporary"].retry_after_seconds > 0
    assert empty.calls == 2  # no retention was granted


def test_all_failed_is_unavailable_but_empty_search_is_not():
    failed = CollectionService([EnabledSource("One", Stub(QuotaExhausted("Out of quota")))],
                               {"Two": "Not approved"})
    assert asyncio.run(failed.collect()).all_unavailable
    assert not asyncio.run(CollectionService([EnabledSource("Empty", Stub([]))]).collect()).all_unavailable


def test_cross_source_url_dedup_is_conservative_and_ranked():
    same_a = listing("A", "a1", "https://jobs.example.org/role/7?utm_source=a", 50000)
    same_b = listing("B", "b9", "https://jobs.example.org/role/7?utm_source=b", 80000)
    separate = listing("B", "b10", "https://jobs.example.org/role/8", 70000)
    report = asyncio.run(CollectionService([EnabledSource("A", Stub([same_a])),
                                            EnabledSource("B", Stub([same_b, separate]))]).collect())
    assert [(job.source, job.source_id) for job in report.jobs] == [("B", "b9"), ("B", "b10")]


def test_concurrent_servers_share_one_inflight_collection():
    source = Stub([listing("One", "1", "https://example.org/job/1")])
    collector = CollectionService([EnabledSource("One", source)])

    async def run_both():
        return await asyncio.gather(collector.collect(), collector.collect())

    first, second = asyncio.run(run_both())
    assert source.calls == 1
    assert first is second


def test_cached_results_expire_at_permitted_retention(monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr(collection, "time", clock)
    source = Stub([listing("One", "1", "https://example.org/job/1")])
    collector = CollectionService([EnabledSource("One", source, permitted_cache_seconds=10)])
    asyncio.run(collector.collect())
    clock.now = 105.0
    assert len(collector.cached_report().jobs) == 1
    assert asyncio.run(collector.collect()).statuses["One"].cached
    clock.now = 110.0
    assert collector.cached_report().all_unavailable
    assert collector.cached_report().jobs == []
    assert not asyncio.run(collector.collect()).statuses["One"].cached
    assert source.calls == 2
