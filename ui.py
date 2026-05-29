"""Discord UI components: modals and persistent views (no domain decisions)."""

import uuid
from datetime import datetime, timezone

import discord
from discord.ui import Modal, TextInput, View
from dateutil import parser as dateutil_parser

import services
from config import BOT_NAME, load_settings
from models import Event, EventStatus, EventSource
from storage import add_event, get_event, update_event, load_events
from meetup import fetch_meetup_event

settings = load_settings()
LOG_CHANNEL_ID = settings.log_channel_id


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

        await update_event(self.event_id, status=EventStatus.COMPLETED)

        dt = event.event_datetime
        embed = discord.Embed(
            title="Post-Event Report",
            color=discord.Color.blurple(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(name="Event", value=event.event_name, inline=False)
        embed.add_field(name="Date", value=dt.strftime("%B %d, %Y at %H:%M UTC"), inline=False)
        embed.add_field(name="Meetup Link", value=event.meetup_link, inline=False)
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

        guild = interaction.client.get_guild(event.guild_id)
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
# Claim view (attached to auto-discovered event announcements)
# ---------------------------------------------------------------------------

class ClaimView(View):
    """Persistent 'I'll cover this' button on an auto-discovered event.

    Claiming sets the submitter and (re)sets the event to pending, so the
    follow-up loop DMs the claimer for a report after the event ends.
    """

    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        self.event_id = event_id

        btn = discord.ui.Button(
            label="I'll cover this",
            style=discord.ButtonStyle.success,
            custom_id=f"claim:{event_id}",
        )
        btn.callback = self._on_click
        self.add_item(btn)

    async def _on_click(self, interaction: discord.Interaction):
        event = get_event(self.event_id)
        if event is None:
            await interaction.response.send_message(
                "This event is no longer available.", ephemeral=True
            )
            return
        if event.submitter_id is not None:
            await interaction.response.send_message(
                "This event has already been claimed.", ephemeral=True
            )
            return

        # Resetting to pending covers the late-claim case (an event that already
        # ended and was marked unclaimed); the follow-up loop re-picks it up.
        await update_event(
            self.event_id,
            submitter_id=interaction.user.id,
            status=EventStatus.PENDING,
        )

        for child in self.children:
            child.disabled = True
        embeds = interaction.message.embeds if interaction.message else []
        if embeds:
            embed = embeds[0]
            embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

        await interaction.followup.send(
            f"You've claimed this event — {BOT_NAME} will DM you for a report after it ends.",
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Event submission modal (opened from /submit_event)
# ---------------------------------------------------------------------------

class EventSubmissionModal(Modal, title="Submit Event"):
    meetup_link = TextInput(
        label="Meetup Link",
        placeholder="https://www.meetup.com/...",
        required=True,
        max_length=500,
    )
    event_name = TextInput(
        label="Event Name (optional)",
        placeholder="Leave blank to pull it from the Meetup link",
        required=False,
        max_length=200,
    )
    event_datetime = TextInput(
        label="Event Date & Time, UTC (optional)",
        placeholder="Blank = use Meetup link; e.g. 2026-04-15 19:00",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Fetching the Meetup page can exceed the modal's ~3s response window,
        # so defer first and answer via followups.
        await interaction.response.defer(ephemeral=True)

        link = self.meetup_link.value.strip()
        name = self.event_name.value.strip()
        dt_text = self.event_datetime.value.strip()

        # De-dup on the canonical event URL so the same Meetup event can't be
        # registered twice.
        if services.is_duplicate(link, load_events()):
            await interaction.followup.send(
                f"That event is already registered — {BOT_NAME} won't add it twice.",
                ephemeral=True,
            )
            return

        # Only hit Meetup if the user left something for us to fill in.
        if not name or not dt_text:
            scraped_name, scraped_start, scraped_end = await fetch_meetup_event(link)
        else:
            scraped_name, scraped_start, scraped_end = None, None, None

        name = name or scraped_name
        if not name:
            await interaction.followup.send(
                "I couldn't read the event name from that Meetup link. "
                "Please re-run `/submit_event` and enter the name yourself.",
                ephemeral=True,
            )
            return

        if dt_text:
            try:
                dt = dateutil_parser.parse(dt_text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except (ValueError, OverflowError):
                await interaction.followup.send(
                    "Could not parse the date/time. Try a format like "
                    "`2026-04-15 19:00` or `April 15, 2026 7:00 PM`.",
                    ephemeral=True,
                )
                return
        else:
            dt = scraped_start

        if dt is None:
            await interaction.followup.send(
                "I couldn't read the event date from that Meetup link. "
                "Please re-run `/submit_event` and enter the date yourself.",
                ephemeral=True,
            )
            return

        if services.is_in_past(dt, datetime.now(timezone.utc)):
            await interaction.followup.send(
                "The event date can't be in the past.", ephemeral=True
            )
            return

        # The follow-up DM fires off the end time, not the start.
        event_end, end_estimated = services.compute_event_end(
            dt, scraped_end, settings.default_event_duration_hours
        )

        event = Event(
            id=str(uuid.uuid4()),
            event_name=name,
            meetup_link=link,
            event_datetime=dt,
            event_end=event_end,
            guild_id=interaction.guild.id,
            status=EventStatus.PENDING,
            source=EventSource.MANUAL,
            submitter_id=interaction.user.id,
        )
        await add_event(event)

        start_str = dt.strftime("%B %d, %Y at %H:%M UTC")
        end_str = event_end.strftime("%B %d, %Y at %H:%M UTC")

        embed = discord.Embed(
            title="Event Registered",
            description=f"**{event.event_name}** has been registered. After the event, {BOT_NAME} will DM you for a follow-up report.",
            color=discord.Color.green(),
        )
        embed.set_author(name=BOT_NAME)
        embed.add_field(name="Starts", value=start_str, inline=True)
        embed.add_field(name="Ends", value=end_str, inline=True)
        embed.add_field(name="Meetup Link", value=event.meetup_link, inline=False)
        embed.set_footer(text=f"Event ID: {event.id[:8]}")

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                print(
                    f"Missing access to log channel {LOG_CHANNEL_ID}; "
                    "couldn't post event registration."
                )

        confirmation = discord.Embed(
            title="Event Submitted",
            description=f"{BOT_NAME} will DM you after the event to collect the follow-up report.",
            color=discord.Color.green(),
        )
        confirmation.set_author(name=BOT_NAME)
        confirmation.add_field(name="Event", value=name, inline=False)
        confirmation.add_field(name="Starts", value=start_str, inline=True)
        confirmation.add_field(name="Ends", value=end_str, inline=True)
        if end_estimated:
            confirmation.set_footer(
                text=f"End time estimated (start + {settings.default_event_duration_hours}h)"
            )
        await interaction.followup.send(embed=confirmation, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.followup.send(
            "Something went wrong. Please try again.", ephemeral=True
        )
        raise error
