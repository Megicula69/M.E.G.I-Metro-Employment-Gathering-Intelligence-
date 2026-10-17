"""Discord slash commands and daily Philippine-time collection."""

import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker

from .collection import CollectionService, EnabledSource
from .database import ServerConfig, make_session_factory
from .daily import MANILA, due_cycle_date, next_daily_run, run_daily_cycle
from .delivery import DeliveryService
from .jooble import JooblePhilippinesSource
from .sources import SampleDataSource


class JobBot(commands.Bot):
    def __init__(self, sessions: sessionmaker[Session], test_guild_id: int | None = None,
                 collection: CollectionService | None = None):
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.sessions = sessions
        self.delivery = DeliveryService(sessions)
        self.test_guild_id = test_guild_id
        self.collection = collection or CollectionService([], {"All sources": "No provider is configured"})
        self._daily_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await self.add_cog(Jobs(self))
        if self.test_guild_id:
            guild = discord.Object(id=self.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self._daily_task = asyncio.create_task(self._daily_loop())

    async def close(self) -> None:
        if self._daily_task:
            self._daily_task.cancel()
        await super().close()

    def _configured_channel(self, config: ServerConfig):
        channel = self.get_channel(config.alert_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        if Jobs._missing_permissions(channel):
            return None
        return channel

    async def _daily_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            now = datetime.now(timezone.utc)
            if due_cycle_date(now) is not None:
                try:
                    await run_daily_cycle(now, self.sessions, self.collection, self.delivery,
                                          self._configured_channel)
                except Exception:
                    logging.exception("Daily collection failed")
            seconds = max(1, (next_daily_run(datetime.now(timezone.utc)) - datetime.now(timezone.utc)).total_seconds())
            await asyncio.sleep(seconds)


class Jobs(commands.GroupCog, group_name="jobs", group_description="NCR job alert controls"):
    setup = app_commands.Group(name="setup", description="Configure job alerts")

    def __init__(self, bot: JobBot):
        self.bot = bot

    @staticmethod
    def _is_admin(interaction: discord.Interaction) -> bool:
        return bool(interaction.guild and isinstance(interaction.user, discord.Member)
                    and interaction.user.guild_permissions.administrator)

    @staticmethod
    def _missing_permissions(channel: discord.TextChannel) -> list[str]:
        member = channel.guild.me
        if member is None:
            return ["bot membership could not be checked"]
        permissions = channel.permissions_for(member)
        return [label for allowed, label in (
            (permissions.view_channel, "View Channel"),
            (permissions.send_messages, "Send Messages"),
            (permissions.embed_links, "Embed Links"),
        ) if not allowed]

    @setup.command(name="channel", description="Save a channel and send a test message")
    @app_commands.describe(channel="Text channel where job cards will be posted")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setup_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("Only server administrators can do this.", ephemeral=True)
            return
        missing = self._missing_permissions(channel)
        if missing:
            await interaction.response.send_message(
                "I need these permissions in that channel: " + ", ".join(missing), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await channel.send("NCR job alerts are set up. This is a test message; sample jobs can be posted with `/jobs preview`.",
                               allowed_mentions=discord.AllowedMentions.none())
            with self.bot.sessions.begin() as session:
                session.merge(ServerConfig(guild_id=interaction.guild_id, alert_channel_id=channel.id))
        except Exception as exc:
            await interaction.followup.send(f"Setup failed: {type(exc).__name__}. Check channel permissions and database settings.", ephemeral=True)
            return
        await interaction.followup.send(f"Alert channel saved: {channel.mention}. Test message sent.", ephemeral=True)

    @app_commands.command(name="preview", description="Post sample NCR job cards in the configured channel")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def preview(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("Only server administrators can do this.", ephemeral=True)
            return
        with self.bot.sessions() as session:
            config = session.get(ServerConfig, interaction.guild_id)
        if config is None:
            await interaction.response.send_message("Run `/jobs setup channel` first.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(config.alert_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The saved text channel is unavailable. Run `/jobs setup channel` again.", ephemeral=True)
            return
        missing = self._missing_permissions(channel)
        if missing:
            await interaction.response.send_message("I need these permissions in the saved channel: " + ", ".join(missing), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.bot.delivery.post_new(interaction.guild_id, channel, SampleDataSource())
        except Exception as exc:
            await interaction.followup.send(
                f"Preview failed ({type(exc).__name__}). No jobs in the failed batch were recorded.",
                ephemeral=True)
            return
        await interaction.followup.send(
            f"Posted {result.sent} sample job(s) in {channel.mention}; skipped {result.skipped_already_sent} already delivered job(s).",
            ephemeral=True)

    @app_commands.command(name="fetch", description="Post real NCR jobs from permitted daily cached results")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def fetch(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await interaction.response.send_message("Only server administrators can do this.", ephemeral=True)
            return
        with self.bot.sessions() as session:
            config = session.get(ServerConfig, interaction.guild_id)
        if config is None:
            await interaction.response.send_message("Run `/jobs setup channel` first.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(config.alert_channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("The saved text channel is unavailable. Run `/jobs setup channel` again.", ephemeral=True)
            return
        missing = self._missing_permissions(channel)
        if missing:
            await interaction.response.send_message("I need these permissions in the saved channel: " + ", ".join(missing), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            collection = self.bot.collection.cached_report()
            status_text = "; ".join(
                f"{name}: {status.kind} ({status.detail}"
                + (f"; retry after ~{status.retry_after_seconds}s" if status.retry_after_seconds is not None else "")
                + ")" for name, status in collection.statuses.items())
            if collection.all_unavailable:
                await interaction.followup.send("Sources unavailable from permitted cache. No real results are currently retained; daily collection runs at 6 PM Philippine time. " + status_text,
                                                ephemeral=True)
                return
            result = await self.bot.delivery.post_jobs(
                interaction.guild_id, channel, collection.jobs,
                cycle_date=datetime.now(MANILA).date(),
                partial_coverage=collection.partial_failure)
        except Exception as exc:
            await interaction.followup.send(
                f"Real batch delivery failed ({type(exc).__name__}). No jobs in the failed batch were recorded.",
                ephemeral=True)
            return
        coverage = "Partial coverage. " if collection.partial_failure else ""
        jobs_text = (f"Posted {result.sent} real eligible NCR job(s) in one message in {channel.mention}; "
                     f"skipped {result.skipped_already_sent} already delivered job(s). ")
        if not collection.jobs:
            jobs_text = "Collection succeeded, but no new eligible NCR jobs with disclosed salaries were returned. "
        elif result.sent == 0:
            jobs_text = "No new eligible NCR jobs with disclosed salaries remain for this server. "
        await interaction.followup.send(
            coverage + jobs_text + status_text,
            ephemeral=True)


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    database_url = os.getenv("DATABASE_URL")
    if not token or not database_url:
        raise SystemExit("Set DISCORD_TOKEN and DATABASE_URL in .env or the environment")
    test_guild = os.getenv("DISCORD_TEST_GUILD_ID", "").strip()
    sessions = make_session_factory(database_url)
    approved = os.getenv("JOOBLE_DISCORD_APPROVED", "false").strip().lower() == "true"
    key = os.getenv("JOOBLE_PH_API_KEY", "").strip()
    enabled = []
    disabled = {
        "JobStreet/SEEK": "Partner API does not document a public job-search feed or Discord reuse",
        "Indeed PH": "No approved public listing-search API or Discord reuse permission",
        "PhilJobNet": "No documented public job-feed API or automated reuse permission",
        "Kalibrr": "Published API is for customer career sites, not general Discord alerts",
    }
    if not approved:
        disabled["Jooble PH"] = "Philippine API key and written Discord republication permission required"
    elif not key:
        disabled["Jooble PH"] = "Philippine API key missing"
    else:
        try:
            cache_seconds = int(os.getenv("JOOBLE_CACHE_SECONDS", "0"))
            if cache_seconds < 0:
                raise ValueError("cache seconds must be nonnegative")
            adapter = JooblePhilippinesSource(key, discord_approved=True,
                                              keywords=os.getenv("JOOBLE_KEYWORDS", "jobs"),
                                              usage_sessions=sessions)
            enabled.append(EnabledSource("Jooble PH", adapter, cache_seconds))
        except ValueError:
            disabled["Jooble PH"] = "Invalid Jooble key, keywords, or approved cache duration"
    collection = CollectionService(enabled, disabled)
    bot = JobBot(sessions, int(test_guild) if test_guild else None, collection)
    bot.run(token)


if __name__ == "__main__":
    main()
