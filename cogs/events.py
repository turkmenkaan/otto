"""Events cog: the /submit_event command and the post-event follow-up loop."""

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import services
from config import BOT_NAME, load_settings
from models import EventStatus
from storage import load_events, update_event
from ui import EventSubmissionModal, PostEventView

settings = load_settings()


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_past_events.start()

    def cog_unload(self):
        self.check_past_events.cancel()

    @app_commands.command(
        name="submit_event",
        description="Register an upcoming event for the organization",
    )
    async def submit_event(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventSubmissionModal())

    # -- background follow-up loop -------------------------------------------

    @tasks.loop(minutes=settings.check_interval_minutes)
    async def check_past_events(self):
        now = datetime.now(timezone.utc)

        for event in services.events_due_for_followup(
            load_events(), now, settings.default_event_duration_hours
        ):
            # Mark as awaiting feedback before attempting DM to avoid duplicate sends
            await update_event(event.id, status=EventStatus.AWAITING_FEEDBACK)

            submitter = await self._fetch_user(event.submitter_id)
            if submitter is None:
                print(f"Could not fetch user {event.submitter_id} for event {event.id}")
                continue

            embed = discord.Embed(
                title="How did your event go?",
                description=(
                    f"Hi, it's {BOT_NAME}! Your event **{event.event_name}** has ended. "
                    "Please submit a quick follow-up report by clicking the button below."
                ),
                color=discord.Color.orange(),
            )
            embed.set_author(name=BOT_NAME)
            embed.add_field(name="Meetup Link", value=event.meetup_link, inline=False)

            view = PostEventView(event.id)
            try:
                await submitter.send(embed=embed, view=view)
            except discord.Forbidden:
                print(
                    f"Could not DM user {submitter} (DMs disabled) for event {event.id}"
                )

    @check_past_events.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _fetch_user(self, user_id: int) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user_id)
        except discord.NotFound:
            return None
