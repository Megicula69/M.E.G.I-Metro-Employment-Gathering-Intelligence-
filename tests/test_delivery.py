import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from job_alert_bot.database import Base, JobDelivery, ServerConfig
from job_alert_bot.delivery import DeliveryService
from job_alert_bot.sources import SampleDataSource
from job_alert_bot.jobs import JobListing, Salary


class FakeChannel:
    def __init__(self, fail_on=None):
        self.messages = []
        self.fail_on = fail_on

    async def send(self, **kwargs):
        if self.fail_on == len(self.messages) + 1:
            raise RuntimeError("simulated send failure")
        self.messages.append(kwargs)
        return type("Message", (), {"id": len(self.messages)})()


def test_per_server_deduplication_and_partial_resume(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all([ServerConfig(guild_id=1, alert_channel_id=10),
                         ServerConfig(guild_id=2, alert_channel_id=20)])
    service = DeliveryService(sessions)
    channel_one = FakeChannel(fail_on=2)
    source = SampleDataSource()

    with pytest.raises(RuntimeError, match="simulated"):
        asyncio.run(service.post_new(1, channel_one, source))
    with sessions() as session:
        assert len(session.scalars(select(JobDelivery).where(JobDelivery.guild_id == 1)).all()) == 1

    channel_one.fail_on = None
    resumed = asyncio.run(service.post_new(1, channel_one, source))
    assert resumed.sent == 3
    assert resumed.skipped_already_sent == 1
    assert len(channel_one.messages) == 4
    assert asyncio.run(service.post_new(1, channel_one, source)).sent == 0

    channel_two = FakeChannel()
    assert asyncio.run(service.post_new(2, channel_two, source)).sent == 4
    assert len(channel_two.messages) == 4
    for message in channel_two.messages:
        button = message["view"].children[0]
        assert button.url.startswith("https://example.com/jobs/")


def test_batch_is_capped_at_fifteen(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'limit.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        session.add(ServerConfig(guild_id=1, alert_channel_id=10))

    class ManyJobs:
        async def fetch_jobs(self):
            sample = (await SampleDataSource().fetch_jobs())[0]
            return [replace(sample, source_id=str(index),
                            application_url=f"https://example.com/jobs/{index}") for index in range(20)]

    channel = FakeChannel()
    result = asyncio.run(DeliveryService(sessions).post_new(1, channel, ManyJobs()))
    assert result.sent == len(channel.messages) == 15


def test_delivery_history_deduplicates_same_url_across_sources_and_servers(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cross.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        session.add_all([ServerConfig(guild_id=1, alert_channel_id=10),
                         ServerConfig(guild_id=2, alert_channel_id=20)])
    first = JobListing("A", "a1", "Engineer", "Employer", "Makati, NCR", True,
                       Salary(), "Hybrid", "Full-time", "https://jobs.example.org/7?utm_source=a")
    second = replace(first, source="B", source_id="b9",
                     application_url="https://jobs.example.org/7?utm_source=b")
    delivery = DeliveryService(sessions)
    one, two = FakeChannel(), FakeChannel()
    assert asyncio.run(delivery.post_jobs(1, one, [first])).sent == 1
    assert asyncio.run(delivery.post_jobs(1, one, [second])).sent == 0
    assert asyncio.run(delivery.post_jobs(2, two, [second])).sent == 1
    assert len(one.messages) == len(two.messages) == 1
