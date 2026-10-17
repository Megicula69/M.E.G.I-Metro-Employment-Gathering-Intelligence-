"""Select and post each new job, recording every successful message immediately."""

import asyncio
from dataclasses import dataclass

import discord
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from .database import JobDelivery
from .jobs import JobListing, SalaryPeriod, canonical_url_hash, monthly_salary_lower, ranked_jobs
from .sources import JobSource


def _short(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _salary_text(job: JobListing) -> str:
    salary = job.salary
    if salary.lower is None or salary.period is None:
        return salary.raw or "Undisclosed"
    amounts = f"{salary.currency.upper()} {salary.lower:,.0f}"
    if salary.upper is not None:
        amounts += f"–{salary.upper:,.0f}"
    text = f"{amounts} / {salary.period.value}"
    comparable = monthly_salary_lower(job)
    if comparable is not None and salary.period != SalaryPeriod.MONTHLY:
        text += f" (from PHP {comparable:,.0f} / month)"
    return text


def job_card(job: JobListing) -> tuple[discord.Embed, discord.ui.View]:
    embed = discord.Embed(title=_short(job.title, 256), color=discord.Color.blue())
    # Keep each field well below 1,024 chars and the whole embed below 6,000.
    embed.add_field(name="Employer", value=_short(job.employer, 500), inline=False)
    embed.add_field(name="Location", value=_short(job.location, 500), inline=True)
    embed.add_field(name="Arrangement", value=_short(job.work_arrangement, 500), inline=True)
    embed.add_field(name="Employment", value=_short(job.employment_type, 500), inline=True)
    embed.add_field(name="Base salary", value=_short(_salary_text(job), 500), inline=False)
    if job.salary.bonus:
        embed.add_field(name="Bonus (separate from base)", value=_short(job.salary.bonus, 500), inline=False)
    embed.set_footer(text=_short(f"Source: {job.source}" +
                                 (f" | Expires: {job.expires_at.date().isoformat()}" if job.expires_at else ""), 256))
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="View / Apply", url=job.application_url))
    return embed, view


@dataclass(frozen=True)
class DeliveryResult:
    sent: int
    skipped_already_sent: int


class DeliveryService:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions
        self._guild_locks: dict[int, asyncio.Lock] = {}

    async def post_new(self, guild_id: int, channel: discord.TextChannel, source: JobSource) -> DeliveryResult:
        return await self.post_jobs(guild_id, channel, await source.fetch_jobs())

    async def post_jobs(self, guild_id: int, channel: discord.TextChannel,
                        jobs: list[JobListing]) -> DeliveryResult:
        lock = self._guild_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            ranked = ranked_jobs(jobs)
            # Deduplicate within a source batch as well as against persisted deliveries.
            unique = []
            seen_keys = set()
            seen_urls = set()
            for job in ranked:
                url_hash = canonical_url_hash(job.application_url)
                if job.key in seen_keys or (url_hash and url_hash in seen_urls):
                    continue
                unique.append(job)
                seen_keys.add(job.key)
                if url_hash:
                    seen_urls.add(url_hash)
            sent = skipped = 0
            for job in unique:
                if sent >= 15:
                    break
                with self.sessions() as session:
                    url_hash = canonical_url_hash(job.application_url)
                    existing = session.scalar(select(JobDelivery.id).where(
                        JobDelivery.guild_id == guild_id,
                        or_(JobDelivery.job_key == job.key,
                            JobDelivery.canonical_url_hash == url_hash)))
                    if existing is not None:
                        skipped += 1
                        continue
                embed, view = job_card(job)
                message = await channel.send(embed=embed, view=view,
                                             allowed_mentions=discord.AllowedMentions.none())
                # Commit after each send. A later send error leaves earlier jobs recorded.
                with self.sessions.begin() as session:
                    session.add(JobDelivery(guild_id=guild_id, job_key=job.key,
                                            canonical_url_hash=url_hash, message_id=message.id))
                sent += 1
            return DeliveryResult(sent, skipped)
