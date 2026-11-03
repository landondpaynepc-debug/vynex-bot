"""Shared Discord panel artwork and attachment delivery."""
from contextlib import ExitStack
from pathlib import Path

import discord

ASSETS = Path(__file__).with_name('assets')
PANEL_COLOR = 0x27364D


def artwork(kind):
    return discord.ui.MediaGallery(discord.MediaGalleryItem(
        f'attachment://vynex-{kind}.png', description=f'Vynex Tweaks — {kind.title()}'))


async def publish_panel(channel, view, kind, *, message=None):
    # Upload with each message edit; Discord manages the image URLs and their expiry.
    # Keep file handles scoped even when an upload fails.
    with ExitStack() as stack:
        files = []
        for name in (kind, 'footer'):
            file = discord.File(ASSETS / f'vynex-{name}.png')
            stack.callback(file.close)
            files.append(file)
        kwargs = dict(view=view, allowed_mentions=discord.AllowedMentions.none())
        if message is not None:
            return await message.edit(attachments=files, **kwargs)
        return await channel.send(files=files, **kwargs)
