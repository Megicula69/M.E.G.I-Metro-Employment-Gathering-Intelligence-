"""Build one compact Discord batch and persist deliveries after send succeeds."""

import asyncio
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

import discord
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from .database import DailyBatch, JobDelivery
from .jobs import JobListing, SalaryPeriod, canonical_url_hash, monthly_salary_lower, ranked_jobs
from .sources import JobSource


def _short(value: str, limit: int) -> str:
    value = discord.utils.escape_markdown(value.strip())
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _salary_text(job: JobListing) -> str:
    salary = job.salary
    if salary.period is None:
        base = salary.raw or f"{salary.currency} {salary.lower:,.0f}"
    else:
        amount = f"{salary.currency} {salary.lower:,.0f}"
        if salary.upper is not None:
            amount += f"–{salary.upper:,.0f}"
        base = f"{amount} / {salary.period.value}"
    comparable = monthly_salary_lower(job)
    if comparable is not None and salary.period != SalaryPeriod.MONTHLY:
        base += f" (PHP {comparable:,.0f}/month comparable)"
    return _short(base, 110)


def _entry(index: int, job: JobListing) -> str:
    details = [_short(job.location, 65)]
    if job.employment_type.strip().lower() not in {"", "unknown", "not specified", "n/a"}:
        details.append(_short(job.employment_type, 35))
    arrangement = job.work_arrangement.strip().lower()
    if arrangement in {"on-site", "onsite", "hybrid", "remote"}:
        details.append("On-site" if arrangement in {"on-site", "onsite"} else arrangement.title())
    link = quote(job.application_url, safe="/:?&=%#@+;,!~*'$_-.")
    lines = [f"**{index}. {_short(job.title, 75)}** — {_short(job.employer, 65)}",
             " · ".join(details), f"Base: {_salary_text(job)}"]
    if job.salary.bonus:
        lines.append(f"Bonus: {_short(job.salary.bonus, 70)}")
    lines.append(f"Source: {_short(job.source, 35)} · [View / Apply]({link})")
    return "\n".join(lines)


def batch_embed(jobs: list[JobListing], *, sample: bool = False,
                partial_coverage: bool = False) -> tuple[discord.Embed, list[JobListing]]:
    title = "SAMPLE NCR jobs — preview" if sample else "NCR jobs — daily alerts"
    selected: list[JobListing] = []
    entries: list[str] = []
    for job in jobs[:15]:
        entry = _entry(len(selected) + 1, job)
        candidate = "\n\n".join([*entries, entry])
        if len(candidate) > 4096 or len(title) + len(candidate) + 100 > 6000:
            break
        selected.append(job)
        entries.append(entry)
    embed = discord.Embed(title=title, description="\n\n".join(entries), color=discord.Color.blue())
    footer = ("Sample data — do not apply" if sample else
              "Partial source coverage — some sources unavailable" if partial_coverage else
              "Listings are attributed to their sources")
    embed.set_footer(text=footer)
    return embed, selected


@dataclass(frozen=True)
class DeliveryResult:
    sent: int
    skipped_already_sent: int


class DeliveryService:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions
        self._guild_locks: dict[int, asyncio.Lock] = {}

    async def post_new(self, guild_id: int, channel: discord.TextChannel, source: JobSource) -> DeliveryResult:
        return await self.post_jobs(guild_id, channel, await source.fetch_jobs(), sample=True)

    async def post_jobs(self, guild_id: int, channel: discord.TextChannel, jobs: list[JobListing],
                        *, sample: bool = False, cycle_date: date | None = None,
                        partial_coverage: bool = False) -> DeliveryResult:
        lock = self._guild_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            ranked = ranked_jobs(jobs)
            unique: list[JobListing] = []
            seen_keys: set[str] = set()
            seen_urls: set[str] = set()
            for job in ranked:
                url_hash = canonical_url_hash(job.application_url)
                if job.key in seen_keys or (url_hash and url_hash in seen_urls):
                    continue
                unique.append(job)
                seen_keys.add(job.key)
                if url_hash:
                    seen_urls.add(url_hash)
            with self.sessions() as session:
                if cycle_date is not None and session.get(DailyBatch, (guild_id, cycle_date)):
                    return DeliveryResult(0, 0)
                available = []
                skipped = 0
                for job in unique:
                    url_hash = canonical_url_hash(job.application_url)
                    existing = session.scalar(select(JobDelivery.id).where(
                        JobDelivery.guild_id == guild_id,
                        or_(JobDelivery.job_key == job.key,
                            JobDelivery.canonical_url_hash == url_hash)))
                    if existing is not None:
                        skipped += 1
                    else:
                        available.append(job)
            embed, selected = batch_embed(available, sample=sample, partial_coverage=partial_coverage)
            if not selected:
                return DeliveryResult(0, skipped)
            message = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            with self.sessions.begin() as session:
                if cycle_date is not None:
                    session.add(DailyBatch(guild_id=guild_id, manila_date=cycle_date, message_id=message.id))
                session.add_all(JobDelivery(guild_id=guild_id, job_key=job.key,
                                            canonical_url_hash=canonical_url_hash(job.application_url),
                                            message_id=message.id) for job in selected)
            return DeliveryResult(len(selected), skipped)
