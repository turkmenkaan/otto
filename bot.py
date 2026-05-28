import discord
from discord import app_commands
from discord.ui import Modal, TextInput, View
from discord.ext import tasks
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from dateutil import parser as dateutil_parser

from storage import add_event, get_event, update_event, get_events_by_status

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", 30))

BOT_NAME = "Otto"

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


# ---------------------------------------------------------------------------
# Post-event modal (opened from DM button)
# ---------------------------------------------------------------------------

class PostEventModal(Modal, title="Post-Event Report"):
    attendees = TextInput(
        label="Number of Attendees",
        placeholder="e.g. 42",
        required=True,
        max_length=10,
    )
    rsvp_count = TextInput(
        label="Number of RSVPs",
        placeholder="e.g. 60",
        required=True,
        max_length=10,
    )
    notes = TextInput(
        label="Notes from the Event",
        placeholder="How did it go? Any highlights, issues, or takeaways?",
        required=False,
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id

    async def on_submit(self, interaction: discord.Interaction):
        if not self.attendees.value.strip().isdigit():
            await interaction.response.send_message(
                "Number of attendees must be a whole number. Please try again.",
                ephemeral=True,
            )
            return
        if not self.rsvp_count.value.strip().isdigit():
            await interaction.response.send_message(
                "Number of RSVPs must be a whole number. Please try again.",
                ephemeral=True,
            )
            return

        event = get_event(self.event_id)
        if not event:
            await interaction.response.send_message("Event not found.", ephemeral=True)
            return

        update_event(self.event_id, {"status": "completed"})

        dt = datetime.fromisoformat(event["event_datetime"])
        embed = discord.Embed(
            title="Post-Event Report",
            color=discord.Color.blurple(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(name="Event", value=event["event_name"], inline=False)
        embed.add_field(name="Date", value=dt.strftime("%B %d, %Y at %H:%M UTC"), inline=False)
        embed.add_field(name="Meetup Link", value=event["meetup_link"], inline=False)
        embed.add_field(name="Attendees", value=self.attendees.value.strip(), inline=True)
        embed.add_field(name="RSVPs", value=self.rsvp_count.value.strip(), inline=True)
        embed.add_field(
            name="Notes",
            value=self.notes.value if self.notes.value else "None",
            inline=False,
        )
        embed.set_footer(
            text=f"Reported by {interaction.user.display_name} ({interaction.user})"
        )
        embed.timestamp = interaction.created_at

        guild = client.get_guild(event["guild_id"])
        if guild:
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(embed=embed)

        await interaction.response.send_message(
            f"Thanks for the report! {BOT_NAME} has logged it.", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            "Something went wrong. Please try again.", ephemeral=True
        )
        raise error


# ---------------------------------------------------------------------------
# Persistent DM view with "Submit Report" button
# ---------------------------------------------------------------------------

class PostEventView(View):
    """
    Persistent view (timeout=None) so the button works even after a bot restart.
    The event ID is encoded in the button's custom_id.
    """

    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        self.event_id = event_id

        btn = discord.ui.Button(
            label="Submit Post-Event Report",
            style=discord.ButtonStyle.primary,
            custom_id=f"post_event:{event_id}",
        )
        btn.callback = self._on_click
        self.add_item(btn)

    async def _on_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PostEventModal(self.event_id))


# ---------------------------------------------------------------------------
# /submit_event command
# ---------------------------------------------------------------------------

class EventSubmissionModal(Modal, title="Submit Event"):
    event_name = TextInput(
        label="Event Name",
        placeholder="e.g. Monthly Community Meetup",
        required=True,
        max_length=200,
    )
    meetup_link = TextInput(
        label="Meetup Link",
        placeholder="https://www.meetup.com/...",
        required=True,
        max_length=500,
    )
    event_datetime = TextInput(
        label="Event Date & Time (UTC)",
        placeholder="e.g. 2026-04-15 19:00 or April 15, 2026 7:00 PM",
        required=True,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            dt = dateutil_parser.parse(self.event_datetime.value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, OverflowError):
            await interaction.response.send_message(
                "Could not parse the date/time. Try a format like `2026-04-15 19:00` or `April 15, 2026 7:00 PM`.",
                ephemeral=True,
            )
            return

        if dt.date() < datetime.now(timezone.utc).date():
            await interaction.response.send_message(
                "The event date can't be in the past.", ephemeral=True
            )
            return

        event = {
            "id": str(uuid.uuid4()),
            "event_name": self.event_name.value,
            "meetup_link": self.meetup_link.value,
            "event_datetime": dt.isoformat(),
            "submitter_id": interaction.user.id,
            "guild_id": interaction.guild.id,
            "status": "pending",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        add_event(event)

        embed = discord.Embed(
            title="Event Registered",
            description=f"**{event['event_name']}** has been registered. After the event, {BOT_NAME} will DM you for a follow-up report.",
            color=discord.Color.green(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(
            name="Date & Time", value=dt.strftime("%B %d, %Y at %H:%M UTC"), inline=False
        )
        embed.add_field(name="Meetup Link", value=event["meetup_link"], inline=False)
        embed.set_footer(text=f"Event ID: {event['id'][:8]}")

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(embed=embed)

        await interaction.response.send_message(
            f"Event submitted! {BOT_NAME} will DM you after the event to collect the follow-up report.",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            "Something went wrong. Please try again.", ephemeral=True
        )
        raise error


@tree.command(
    name="submit_event",
    description="Register an upcoming event for the organization",
)
async def submit_event(interaction: discord.Interaction):
    await interaction.response.send_modal(EventSubmissionModal())


# ---------------------------------------------------------------------------
# Background task: check for past events and DM submitters
# ---------------------------------------------------------------------------

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_past_events():
    now = datetime.now(timezone.utc)
    pending_events = get_events_by_status("pending")

    for event in pending_events:
        event_dt = datetime.fromisoformat(event["event_datetime"])
        if now < event_dt:
            continue

        # Mark as awaiting feedback before attempting DM to avoid duplicate sends
        update_event(event["id"], {"status": "awaiting_feedback"})

        submitter = await _fetch_user(event["submitter_id"])
        if submitter is None:
            print(f"Could not fetch user {event['submitter_id']} for event {event['id']}")
            continue

        embed = discord.Embed(
            title="How did your event go?",
            description=(
                f"Hi, it's {BOT_NAME}! Your event **{event['event_name']}** has ended. "
                "Please submit a quick follow-up report by clicking the button below."
            ),
            color=discord.Color.orange(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(name="Meetup Link", value=event["meetup_link"], inline=False)

        view = PostEventView(event["id"])
        try:
            await submitter.send(embed=embed, view=view)
        except discord.Forbidden:
            print(
                f"Could not DM user {submitter} (DMs disabled) for event {event['id']}"
            )


async def _fetch_user(user_id: int) -> discord.User | None:
    try:
        return await client.fetch_user(user_id)
    except discord.NotFound:
        return None


@check_past_events.before_loop
async def before_check():
    await client.wait_until_ready()


# ---------------------------------------------------------------------------
# Bot startup
# ---------------------------------------------------------------------------

@client.event
async def on_ready():
    # Re-register persistent views for all events awaiting feedback
    # so buttons in existing DMs still work after a restart
    for event in get_events_by_status("awaiting_feedback"):
        client.add_view(PostEventView(event["id"]))

    await tree.sync()
    check_past_events.start()
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"Checking for past events every {CHECK_INTERVAL_MINUTES} minutes.")


client.run(TOKEN)
