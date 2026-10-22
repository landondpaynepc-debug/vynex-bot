"""Consistent Components V2 text responses."""
import discord

TICKET_COLOR = 0x2B2D31


def text_view(text):
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(discord.ui.TextDisplay(text), accent_colour=TICKET_COLOR))
    return view


async def send_text(sender, text, **kwargs):
    kwargs.setdefault('allowed_mentions', discord.AllowedMentions.none())
    result = None
    for start in range(0, max(1, len(text)), 3500):
        result = await sender(view=text_view(text[start:start+3500]), **kwargs)
    return result
