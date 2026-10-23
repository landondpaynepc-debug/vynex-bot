"""Reviews and giveaways with durable Discord-backed giveaway state."""
import asyncio
from contextlib import suppress
import io
import json
import logging
import re
import secrets
import time

import discord

from event_logs import LOG_CHANNEL_ID
from ui_messages import TICKET_COLOR, send_text, text_view
from tickets import NO_MENTIONS

ENTRY_ID = 'vynex:giveaway:enter:v1'
STATE_FILE = 'vynex-giveaway.json'


def duration_seconds(value):
    match = re.fullmatch(r'\s*(\d+)\s*([mhd])\s*', value.lower())
    if not match:
        raise ValueError('Use a duration such as 10m, 2h or 7d.')
    seconds = int(match[1]) * {'m': 60, 'h': 3600, 'd': 86400}[match[2]]
    if not 60 <= seconds <= 30 * 86400:
        raise ValueError('Duration must be between 1 minute and 30 days.')
    return seconds


def review_view(user, stars, application, review):
    rating = '★' * stars + '☆' * (5 - stars)
    name = discord.utils.escape_markdown(str(user))
    return text_view(f'## {application} — Member Review\n'
        f'**Reviewer:** {name} ({user.id})\n**Rating:** {rating} **{stars}/5**\n\n'
        f'{discord.utils.escape_markdown(review)}')


class EnterButton(discord.ui.Button):
    def __init__(self, manager, ended=False):
        super().__init__(label='Giveaway ended' if ended else 'Enter Giveaway',
                         style=discord.ButtonStyle.secondary, custom_id=ENTRY_ID, disabled=ended)
        self.manager = manager

    async def callback(self, interaction):
        await self.manager.enter(interaction)


class GiveawayView(discord.ui.LayoutView):
    def __init__(self, manager, state):
        super().__init__(timeout=None)
        ended = state['ended']
        text = (f'## Giveaway — {discord.utils.escape_markdown(state["prize"])}\n'
                f'{discord.utils.escape_mentions(state["description"])}\n\n'
                f'**Hosted by:** <@{state["host"]}>\n'
                f'**Entries:** {len(state["entries"])}\n'
                f'**{"Ended" if ended else "Ends"}:** <t:{state["ends"]}:F> (<t:{state["ends"]}:R>)\n')
        if ended:
            winner = state['winner']
            text += (f'\n**Winner:** <@{winner}> — {discord.utils.escape_markdown(state["entries"][winner])}\nCongratulations!'
                     if winner else '\n**No winner:** Nobody entered this giveaway.')
        else:
            text += '\nPress **Enter Giveaway** below. One entry per member.'
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text),
            discord.ui.Separator(visible=False), discord.ui.ActionRow(EnterButton(manager, ended)),
            accent_colour=TICKET_COLOR))


class GiveawayManager:
    def __init__(self, bot, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.states = {}
        self.lock = asyncio.Lock()
        self.task = None
        self.loaded = False

    def register_view(self):
        self.bot.add_view(GiveawayView(self, dict(ended=False, prize='Giveaway', description='',
            host=0, entries={}, ends=0)))

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def registry(self):
        channel = self.bot.get_channel(LOG_CHANNEL_ID) or await self.bot.fetch_channel(LOG_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise RuntimeError('Giveaway storage requires the configured staff logs channel.')
        return channel

    def file(self, state):
        return discord.File(io.BytesIO(json.dumps(state, ensure_ascii=False).encode('utf-8')), filename=STATE_FILE)

    async def save(self, state, record=None):
        channel = await self.registry()
        file = self.file(state)
        view = text_view(f'### Giveaway record\nPrize: {discord.utils.escape_markdown(state["prize"])}\n'
            f'Host: {state["host"]}\nChannel: {state["channel"]}\nMessage: {state["message"]}\n'
            f'Entries: {len(state["entries"])}\nStatus: {"Ended" if state["ended"] else "Active"}\n'
            '-# Vynex giveaway recovery record • Keep this message and its attachment.')
        try:
            if record:
                await record.edit(view=view, attachments=[file], allowed_mentions=NO_MENTIONS)
                return record
            return await channel.send(view=view, file=file, allowed_mentions=NO_MENTIONS)
        finally:
            file.close()

    async def load(self):
        channel = await self.registry()
        recovered = {}
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.id != self.bot.user.id:
                continue
            attachment = next((a for a in message.attachments if a.filename == STATE_FILE), None)
            if attachment is None:
                continue
            try:
                state = json.loads(await attachment.read())
                if state['guild'] == self.guild_id and (not state['ended'] or not state['announced']):
                    recovered[state['message']] = (state, message)
            except (ValueError, KeyError, TypeError):
                logging.error('Invalid giveaway recovery record %s; record left intact.', message.id)
        self.states.update(recovered)
        self.loaded = True

    async def create(self, interaction, prize, description, seconds):
        async with self.lock:
            if not self.loaded:
                await self.load()
            # Verify durable storage before posting a giveaway.
            await self.registry()
            state = dict(version=1, guild=self.guild_id, channel=interaction.channel_id, message=0,
                         host=interaction.user.id, prize=prize, description=description,
                         ends=int(time.time()) + seconds, entries={}, ended=False, winner=None, announced=False)
            message = await interaction.channel.send(view=GiveawayView(self, state), allowed_mentions=NO_MENTIONS)
            state['message'] = message.id
            try:
                record = await self.save(state)
            except Exception:
                # An untracked giveaway must not continue accepting entries.
                state['ended'] = True
                with suppress(discord.HTTPException):
                    await message.delete()
                raise
            self.states[message.id] = (state, record)
            return message

    async def enter(self, interaction):
        if interaction.guild_id != self.guild_id or interaction.user.bot:
            return await send_text(interaction.response.send_message, 'Only members of this server can enter.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if not self.loaded:
                await send_text(interaction.followup.send, 'Giveaways are recovering. Try again shortly.', ephemeral=True)
                return
            item = self.states.get(interaction.message.id)
            if item is None or item[0]['ended'] or time.time() >= item[0]['ends']:
                return await send_text(interaction.followup.send, 'This giveaway has ended.', ephemeral=True)
            state, record = item
            key = str(interaction.user.id)
            if key in state['entries']:
                return await send_text(interaction.followup.send, 'You are already entered. Each member gets one entry.', ephemeral=True)
            updated = {**state, 'entries': {**state['entries'], key: str(interaction.user)}}
            try:
                await self.save(updated, record)
            except (discord.HTTPException, RuntimeError):
                return await send_text(interaction.followup.send, 'Your entry could not be saved. Please try again.', ephemeral=True)
            self.states[state['message']] = (updated, record)
            with suppress(discord.HTTPException):
                await interaction.message.edit(view=GiveawayView(self, updated), allowed_mentions=NO_MENTIONS)
            await send_text(interaction.followup.send, 'You are entered! Good luck.', ephemeral=True)

    async def tick(self):
        async with self.lock:
            if not self.loaded:
                await self.load()
            for ident, (state, record) in list(self.states.items()):
                if not state['ended'] and time.time() < state['ends']:
                    continue
                try:
                    if not state['ended']:
                        state = {**state, 'ended': True,
                                 'winner': secrets.choice(list(state['entries'])) if state['entries'] else None}
                        # Save the result before announcing, so recovery never redraws a winner.
                        await self.save(state, record)
                        self.states[ident] = (state, record)
                    channel = self.bot.get_channel(state['channel']) or await self.bot.fetch_channel(state['channel'])
                    message = await channel.fetch_message(ident)
                    winner = state['winner']
                    await message.edit(view=GiveawayView(self, state), allowed_mentions=discord.AllowedMentions(
                        everyone=False, users=[discord.Object(id=int(winner))] if winner else False, roles=False))
                    state = {**state, 'announced': True}
                    await self.save(state, record)
                    del self.states[ident]
                except (discord.HTTPException, RuntimeError):
                    logging.error('Giveaway %s update failed; saved result retained for retry.', ident)

    async def run(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.tick()
            except (discord.HTTPException, RuntimeError):
                logging.error('Giveaway recovery failed. Check staff logs channel permissions.')
            await asyncio.sleep(15)
