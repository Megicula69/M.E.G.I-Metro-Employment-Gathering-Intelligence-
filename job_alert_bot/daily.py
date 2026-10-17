"""One persisted provider collection at 18:00 Asia/Manila per day."""

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .collection import CollectionResult, CollectionService
from .database import CollectionCycle, ServerConfig
from .delivery import DeliveryService


LOG = logging.getLogger(__name__)
MANILA = ZoneInfo("Asia/Manila")


def due_cycle_date(now: datetime) -> date | None:
    local = now.astimezone(MANILA)
    return local.date() if local.time() >= time(18) else None


def next_daily_run(now: datetime) -> datetime:
    local = now.astimezone(MANILA)
    day = local.date() if local.time() < time(18) else local.date() + timedelta(days=1)
    return datetime.combine(day, time(18), MANILA)


def claim_cycle(sessions: sessionmaker[Session], day: date) -> bool:
    try:
        with sessions.begin() as session:
            session.add(CollectionCycle(manila_date=day))
        return True
    except IntegrityError:
        return False


async def run_daily_cycle(now: datetime, sessions: sessionmaker[Session],
                          collection: CollectionService, delivery: DeliveryService,
                          resolve_channel) -> CollectionResult | None:
    day = due_cycle_date(now)
    if day is None or not claim_cycle(sessions, day):
        return None
    outcome = "sources_unavailable"
    try:
        report = await collection.collect()
        if report.all_unavailable:
            LOG.warning("Daily NCR collection: sources unavailable: %s", report.statuses)
            return report
        if not report.jobs:
            outcome = "no_eligible_jobs"
            LOG.info("Daily NCR collection: no new eligible jobs with disclosed salaries")
            return report
        outcome = "partial_coverage" if report.partial_failure else "collected"
        with sessions() as session:
            configs = session.scalars(select(ServerConfig)).all()
        for config in configs:
            try:
                channel = resolve_channel(config)
                if channel is None:
                    LOG.warning("Configured channel unavailable for server %s", config.guild_id)
                    continue
                await delivery.post_jobs(config.guild_id, channel, report.jobs, cycle_date=day,
                                         partial_coverage=report.partial_failure)
            except Exception:
                LOG.exception("Daily batch delivery failed for server %s", config.guild_id)
        return report
    finally:
        with sessions.begin() as session:
            cycle = session.get(CollectionCycle, day)
            cycle.outcome = outcome
