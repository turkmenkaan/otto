"""Entry point: build the bot, load cogs, register persistent views, run."""

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import load_settings
from models import EventStatus, EventSource
from storage import get_events_by_status, load_events
from ui import PostEventView, ClaimView
from cogs.events import EventsCog
from cogs.groups import GroupsCog

load_dotenv()
settings = load_settings()


class OttoBot(commands.Bot):
    def __init__(self):
        # Slash-only bot: when_mentioned avoids needing the message_content intent.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )

    async def setup_hook(self):
        self._register_persistent_views()
        await self.add_cog(EventsCog(self))
        await self.add_cog(GroupsCog(self))
        await self.tree.sync()

    def _register_persistent_views(self):
        # Post-event report buttons for events awaiting feedback.
        for event in get_events_by_status(EventStatus.AWAITING_FEEDBACK):
            self.add_view(PostEventView(event.id))
        # Claim buttons for auto-discovered events still up for grabs.
        for event in load_events():
            if (
                event.source == EventSource.AUTO
                and event.submitter_id is None
                and event.status in (EventStatus.PENDING, EventStatus.UNCLAIMED)
            ):
                self.add_view(ClaimView(event.id))

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print(f"Checking for past events every {settings.check_interval_minutes} minutes.")


bot = OttoBot()
bot.run(settings.token)
