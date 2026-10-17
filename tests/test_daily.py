import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from job_alert_bot.collection import CollectionService, EnabledSource
from job_alert_bot.daily import claim_cycle, due_cycle_date, next_daily_run, run_daily_cycle
from job_alert_bot.database import Base, CollectionCycle, ServerConfig
from job_alert_bot.delivery import DeliveryService
from job_alert_bot.sources import SampleDataSource


def test_manila_six_pm_schedule():
    before = datetime(2026, 10, 17, 9, 59, tzinfo=timezone.utc)
    at = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)
    assert due_cycle_date(before) is None
    assert due_cycle_date(at).isoformat() == "2026-10-17"
    assert next_daily_run(before) == at
    assert next_daily_run(at) == datetime(2026, 10, 18, 10, tzinfo=timezone.utc)


def test_restart_claim_and_shared_collection(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'daily.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all([ServerConfig(guild_id=1, alert_channel_id=10),
                         ServerConfig(guild_id=2, alert_channel_id=20)])
    calls = []

    class Source:
        async def fetch_jobs(self):
            calls.append(1)
            return await SampleDataSource().fetch_jobs()

    class Channel:
        def __init__(self):
            self.messages = []

        async def send(self, **kwargs):
            self.messages.append(kwargs)
            return type("Message", (), {"id": len(self.messages)})()

    channels = {1: Channel(), 2: Channel()}
    now = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
    collection = CollectionService([EnabledSource("fake", Source(), 0)])
    delivery = DeliveryService(sessions)
    resolve = lambda config: channels[config.guild_id]
    asyncio.run(run_daily_cycle(now, sessions, collection, delivery, resolve))
    assert calls == [1]
    assert all(len(channel.messages) == 1 for channel in channels.values())
    # Recreated services model a process restart; persisted claim prevents another request.
    fresh = CollectionService([EnabledSource("fake", Source(), 0)])
    assert asyncio.run(run_daily_cycle(now, sessions, fresh, DeliveryService(sessions), resolve)) is None
    assert calls == [1]
    with sessions() as session:
        assert session.scalar(select(CollectionCycle)).outcome == "collected"


def test_claim_is_persisted_before_provider_error(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'claim.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    day = datetime(2026, 10, 17).date()
    assert claim_cycle(sessions, day)
    assert not claim_cycle(sessions, day)
