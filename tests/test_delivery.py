import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from job_alert_bot.database import Base, DailyBatch, JobDelivery, ServerConfig
from job_alert_bot.delivery import DeliveryService
from job_alert_bot.jobs import Salary, SalaryPeriod
from job_alert_bot.sources import SampleDataSource


class FakeChannel:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    async def send(self, **kwargs):
        if self.fail:
            raise RuntimeError("send failed")
        self.messages.append(kwargs)
        return type("Message", (), {"id": len(self.messages)})()


def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all([ServerConfig(guild_id=1, alert_channel_id=10),
                         ServerConfig(guild_id=2, alert_channel_id=20)])
    return sessions


def test_one_message_links_and_tracking_after_success(tmp_path):
    sessions = setup(tmp_path)
    jobs = asyncio.run(SampleDataSource().fetch_jobs())
    service = DeliveryService(sessions)
    channel = FakeChannel(fail=True)
    with pytest.raises(RuntimeError):
        asyncio.run(service.post_jobs(1, channel, jobs, cycle_date=date(2026, 10, 17)))
    with sessions() as session:
        assert session.scalars(select(JobDelivery)).all() == []
    channel.fail = False
    result = asyncio.run(service.post_jobs(1, channel, jobs, cycle_date=date(2026, 10, 17)))
    assert result.sent == len(jobs)
    assert len(channel.messages) == 1
    description = channel.messages[0]["embed"].description
    for job in jobs:
        assert job.application_url in description
    with sessions() as session:
        deliveries = session.scalars(select(JobDelivery)).all()
        assert len(deliveries) == len(jobs)
        assert {item.message_id for item in deliveries} == {1}
        assert session.get(DailyBatch, (1, date(2026, 10, 17))).message_id == 1
    assert asyncio.run(service.post_jobs(1, channel, jobs, cycle_date=date(2026, 10, 17))).sent == 0
    assert len(channel.messages) == 1
    other = FakeChannel()
    assert asyncio.run(service.post_jobs(2, other, jobs, cycle_date=date(2026, 10, 17))).sent == len(jobs)
    assert len(other.messages) == 1


def test_limit_arrangement_and_sample_label(tmp_path):
    sessions = setup(tmp_path)
    original = asyncio.run(SampleDataSource().fetch_jobs())[0]
    jobs = [replace(original, source_id=str(index), title="X" * 300,
                    employer="Y" * 300, location="Makati " + "Z" * 300,
                    work_arrangement="Not specified",
                    application_url=f"https://example.com/jobs/{index}") for index in range(30)]
    channel = FakeChannel()
    result = asyncio.run(DeliveryService(sessions).post_jobs(1, channel, jobs, sample=True))
    assert 1 <= result.sent <= 15
    embed = channel.messages[0]["embed"]
    assert "SAMPLE" in embed.title
    assert len(embed.description) <= 4096
    assert "Not specified" not in embed.description
    assert "Arrangement" not in embed.description
    assert embed.description.count("[View / Apply]") == result.sent


def test_cross_source_url_duplicate_per_server(tmp_path):
    sessions = setup(tmp_path)
    first = asyncio.run(SampleDataSource().fetch_jobs())[0]
    second = replace(first, source="Other", source_id="other",
                     application_url=first.application_url + "?utm_source=elsewhere")
    service = DeliveryService(sessions)
    one, two = FakeChannel(), FakeChannel()
    assert asyncio.run(service.post_jobs(1, one, [first, second])).sent == 1
    assert asyncio.run(service.post_jobs(1, one, [second])).sent == 0
    assert asyncio.run(service.post_jobs(2, two, [second])).sent == 1


@pytest.mark.parametrize("salary", [
    Salary(), Salary(raw="Negotiable"), Salary(lower=Decimal("0")),
    Salary(lower=Decimal("-2")), Salary(raw="Commission only"),
    Salary(lower=Decimal("NaN")),
])
def test_undisclosed_or_invalid_salary_excluded(tmp_path, salary):
    sessions = setup(tmp_path)
    job = replace(asyncio.run(SampleDataSource().fetch_jobs())[0], salary=salary)
    channel = FakeChannel()
    assert asyncio.run(DeliveryService(sessions).post_jobs(1, channel, [job])).sent == 0
    assert channel.messages == []


def test_noncomparable_positive_base_follows_monthly(tmp_path):
    sessions = setup(tmp_path)
    first = asyncio.run(SampleDataSource().fetch_jobs())[0]
    unknown = replace(first, source_id="unknown", salary=Salary(lower=Decimal("100000"),
                      period=None, raw="PHP 100,000"), application_url="https://example.com/u")
    monthly = replace(first, source_id="monthly", salary=Salary(lower=Decimal("80000"),
                      period=SalaryPeriod.MONTHLY), application_url="https://example.com/m")
    channel = FakeChannel()
    asyncio.run(DeliveryService(sessions).post_jobs(1, channel, [unknown, monthly]))
    text = channel.messages[0]["embed"].description
    assert text.index("example.com/m") < text.index("example.com/u")


def test_partial_coverage_visible_in_batch(tmp_path):
    sessions = setup(tmp_path)
    jobs = asyncio.run(SampleDataSource().fetch_jobs())
    channel = FakeChannel()
    asyncio.run(DeliveryService(sessions).post_jobs(1, channel, jobs, partial_coverage=True))
    assert "Partial source coverage" in channel.messages[0]["embed"].footer.text
