"""Publish the community rules as reusable, size-limited Components V2 messages."""
import asyncio
from pathlib import Path
import re

import discord

from tickets import NO_MENTIONS, TICKET_COLOR

RULES_CHANNEL_ID = 1562749964017336391
MARKER = '-# Vynex community rules · Part '
RULES_TEXT = Path(__file__).with_name('community_rules.txt').read_text(encoding='utf-8').strip()


def rules_parts():
    # Leave room for the identifying footer within Discord's total text limit.
    parts, current = [], ''
    for paragraph in RULES_TEXT.split('\n\n'):
        while len(paragraph) > 3600:
            if current:
                parts.append(current)
                current = ''
            end = paragraph.rfind('\n', 0, 3600)
            if end <= 0:
                end = 3600
            parts.append(paragraph[:end])
            paragraph = paragraph[end:].lstrip('\n')
        candidate = f'{current}\n\n{paragraph}' if current else paragraph
        if len(candidate) > 3600:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


class RulesView(discord.ui.LayoutView):
    def __init__(self, text, index, total):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(text),
            discord.ui.Separator(visible=False),
            discord.ui.TextDisplay(f'{MARKER}{index}/{total}'),
            accent_colour=TICKET_COLOR))


def rules_index(message):
    def walk(items):
        for item in items:
            match = re.fullmatch(re.escape(MARKER) + r'(\d+)/(\d+)', item.get('content', ''))
            if match:
                return int(match[1])
            found = walk(item.get('components', []))
            if found is not None:
                return found
        return None
    return walk([item.to_dict() for item in message.components])


class RulesManager:
    def __init__(self, bot, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.lock = asyncio.Lock()

    async def ensure_rules(self):
        async with self.lock:
            channel = self.bot.get_channel(RULES_CHANNEL_ID) or await self.bot.fetch_channel(RULES_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
                raise RuntimeError('Rules channel must be a text channel in the configured server.')
            existing = {}
            async for message in channel.history(limit=None, oldest_first=True):
                if message.author.id == self.bot.user.id:
                    index = rules_index(message)
                    if index is not None:
                        existing.setdefault(index, message)
            parts = rules_parts()
            published = []
            for index, text in enumerate(parts, 1):
                view = RulesView(text, index, len(parts))
                if index in existing:
                    message = existing[index]
                    await message.edit(view=view, allowed_mentions=NO_MENTIONS)
                else:
                    message = await channel.send(view=view, allowed_mentions=NO_MENTIONS)
                published.append(message)
            return published
