"""Entry point: build the bot, load cogs, register persistent views, run."""

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import load_settings
from models import EventStatus
from storage import get_events_by_status
from ui import PostEventView
from cogs.events import EventsCog

load_dotenv()
settings = load_settings()


class OttoBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        # Re-register persistent views so DM buttons survive a restart.
        for event in get_events_by_status(EventStatus.AWAITING_FEEDBACK):
            self.add_view(PostEventView(event.id))

        await self.add_cog(EventsCog(self))
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print(f"Checking for past events every {settings.check_interval_minutes} minutes.")


bot = OttoBot()
bot.run(settings.token)
