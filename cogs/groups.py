"""Groups cog: watch Meetup groups and auto-discover their new events."""

import uuid
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import services
from config import BOT_NAME, load_settings
from models import Event, EventStatus, EventSource, Group
from storage import (
    add_event,
    add_group,
    get_group,
    load_events,
    load_groups,
    remove_group,
    update_group,
)
from meetup import fetch_group_event_urls, fetch_meetup_event, normalize_group_input
from ui import ClaimView

settings = load_settings()


class GroupsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_meetup_groups.start()

    def cog_unload(self):
        self.poll_meetup_groups.cancel()

    # -- commands (Manage Server only) ---------------------------------------

    @app_commands.command(
        name="watch_group",
        description="Watch a Meetup group and auto-post its new events",
    )
    @app_commands.describe(
        group="Meetup group URL or slug (e.g. nova-code-coffee)",
        channel="Channel to announce new events in (defaults to this channel)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def watch_group(
        self,
        interaction: discord.Interaction,
        group: str,
        channel: discord.TextChannel | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        slug, url = normalize_group_input(group)
        if not slug:
            await interaction.followup.send(
                "I couldn't read that — give me a Meetup group URL or slug.",
                ephemeral=True,
            )
            return
        if get_group(slug, interaction.guild.id):
            await interaction.followup.send(
                f"Already watching **{slug}**.", ephemeral=True
            )
            return

        target = channel or interaction.channel
        watched = Group(
            slug=slug,
            url=url,
            guild_id=interaction.guild.id,
            channel_id=target.id,
            added_by=interaction.user.id,
        )
        await add_group(watched)

        # Seed silently: record current events without announcing them, so only
        # events posted *after* now will be announced.
        recorded = await self._ingest(watched, announce=False)
        await update_group(slug, interaction.guild.id, seeded=True)

        await interaction.followup.send(
            f"Now watching **{slug}** — recorded {recorded} current event(s); "
            f"new ones will post to {target.mention}.",
            ephemeral=True,
        )

    @app_commands.command(
        name="unwatch_group", description="Stop watching a Meetup group"
    )
    @app_commands.describe(group="Meetup group URL or slug")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unwatch_group(self, interaction: discord.Interaction, group: str):
        slug, _ = normalize_group_input(group)
        removed = await remove_group(slug, interaction.guild.id)
        message = (
            f"Stopped watching **{slug}**."
            if removed
            else f"I wasn't watching **{slug}**."
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(
        name="list_groups", description="List the Meetup groups being watched"
    )
    async def list_groups(self, interaction: discord.Interaction):
        groups = [g for g in load_groups() if g.guild_id == interaction.guild.id]
        if not groups:
            await interaction.response.send_message(
                "Not watching any groups yet. Use `/watch_group` to add one.",
                ephemeral=True,
            )
            return
        lines = [f"• **{g.slug}** → <#{g.channel_id}>" for g in groups]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need the **Manage Server** permission to use this."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        else:
            raise error

    # -- background discovery loop -------------------------------------------

    @tasks.loop(minutes=settings.group_poll_interval_minutes)
    async def poll_meetup_groups(self):
        for group in load_groups():
            try:
                added = await self._ingest(group, announce=group.seeded)
                if not group.seeded:
                    await update_group(group.slug, group.guild_id, seeded=True)
                print(f"[poll] {group.slug}: {added} new event(s)")
            except Exception as error:  # one bad group must not break the rest
                print(f"[poll] error for group {group.slug}: {error!r}")

    @poll_meetup_groups.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # -- shared discovery ----------------------------------------------------

    async def _ingest(self, group: Group, announce: bool) -> int:
        """Discover new events for a group, store them, optionally announce."""
        urls = await fetch_group_event_urls(group.url)
        known = services.known_event_keys(load_events())
        added = 0
        for url in services.select_new_event_urls(urls, known):
            name, start, end = await fetch_meetup_event(url)
            if not name or start is None:
                continue
            event_end, _ = services.compute_event_end(
                start, end, settings.default_event_duration_hours
            )
            event = Event(
                id=str(uuid.uuid4()),
                event_name=name,
                meetup_link=url,
                event_datetime=start,
                event_end=event_end,
                guild_id=group.guild_id,
                status=EventStatus.PENDING,
                source=EventSource.AUTO,
                submitter_id=None,
                group=group.slug,
            )
            await add_event(event)
            added += 1
            if announce:
                await self._announce(group, event)
        return added

    async def _announce(self, group: Group, event: Event):
        channel = self.bot.get_channel(group.channel_id)
        if channel is None:
            return

        embed = discord.Embed(
            title="New event posted",
            description=f"**{event.event_name}**",
            color=discord.Color.blue(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(
            name="Starts",
            value=event.event_datetime.strftime("%B %d, %Y at %H:%M UTC"),
            inline=True,
        )
        if event.event_end:
            embed.add_field(
                name="Ends",
                value=event.event_end.strftime("%B %d, %Y at %H:%M UTC"),
                inline=True,
            )
        embed.add_field(name="Meetup Link", value=event.meetup_link, inline=False)
        embed.set_footer(text=f"From {group.slug} • claim it to report afterward")

        try:
            await channel.send(embed=embed, view=ClaimView(event.id))
        except discord.Forbidden:
            print(
                f"Missing access to announce channel {group.channel_id} "
                f"for group {group.slug}"
            )
