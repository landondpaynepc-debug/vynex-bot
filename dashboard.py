"""Public, persistent Components V2 community dashboard."""
import asyncio
import logging

import discord
from ui_messages import send_text
from panel_style import PANEL_COLOR, artwork, publish_panel

from rules import rules_parts
from tickets import PANEL_CHANNEL_ID, NO_MENTIONS, TICKET_COLOR, has_component

DASHBOARD_CHANNEL_ID = 1562754545631887461
MENU_ID = 'vynex:dashboard:menu:v1'
ABOUT = '''# About Vynex Tweaks

*Engineered for Performance*
> Every tweak is hand-tuned and battle-tested for maximum performance.

*Latency Reduction*
> Kill input lag and shave milliseconds off your response time with our tuned network stack.

*CPU Optimization*
> Free up cores and prioritize game threads so your rig runs at peak efficiency.

*FPS Boosting*
> Squeeze out every frame with hand-tuned GPU and rendering configurations.

*Stability Hardening*
> Eliminate stutters and crashes with system-level stability improvements.

*Fast Boot Times*
> Cut down startup bloat and get into your games faster than ever.

*Competitive Edge*
> Built for ranked play — every tweak is engineered to give you the upper hand.

*Vynex Tweaks is more than a tweaking tool — it's a project built around making PC optimization easier for everyone.*

-# *Optimize. Refine. Perform.*'''


class DashboardSelect(discord.ui.Select):
    def __init__(self, manager):
        self.manager = manager
        super().__init__(custom_id=MENU_ID, placeholder='Explore the community', options=[
            discord.SelectOption(label='About Vynex Tweaks', value='about', description='The project, our tools, and what we do'),
            discord.SelectOption(label='Rules', value='rules', description='Community guidelines and server policies'),
        ])

    async def callback(self, interaction):
        await self.manager.choose(interaction, self.values[0])


class DashboardView(discord.ui.LayoutView):
    def __init__(self, manager, text=None):
        super().__init__(timeout=None)
        if text is None:
            self.add_item(discord.ui.Container(
                artwork('community'),
                discord.ui.TextDisplay('### Vynex Community\n'
                    'Your home for Vynex Tweaks. Get to know the project and find your way around.'),
                discord.ui.TextDisplay('**Start here**\n'
                    '• **About Vynex** — our tools and the ideas behind them.\n'
                    '• **Community rules** — a few guidelines to keep things running smoothly.'),
                discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                discord.ui.TextDisplay('-# Choose a section below. Only you can see the page you open.'),
                discord.ui.ActionRow(DashboardSelect(manager)),
                artwork('footer'), accent_colour=PANEL_COLOR))
            return
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(text), discord.ui.Separator(visible=False),
            discord.ui.ActionRow(DashboardSelect(manager)), accent_colour=TICKET_COLOR))


class RulesPager(discord.ui.LayoutView):
    def __init__(self, manager, owner_id, page=0):
        super().__init__(timeout=600)
        self.manager, self.owner_id, self.page = manager, owner_id, page
        parts = rules_parts()
        previous = discord.ui.Button(label='Previous', style=discord.ButtonStyle.secondary, disabled=page == 0)
        next_button = discord.ui.Button(label='Next', style=discord.ButtonStyle.secondary, disabled=page == len(parts)-1)
        previous.callback = self.previous
        next_button.callback = self.next
        self.add_item(discord.ui.Container(
            discord.ui.TextDisplay(parts[page]), discord.ui.Separator(visible=False),
            discord.ui.TextDisplay(f'-# Community Rules · Page {page+1}/{len(parts)}'),
            discord.ui.ActionRow(previous, next_button),
            discord.ui.ActionRow(DashboardSelect(manager)), accent_colour=TICKET_COLOR))

    async def move(self, interaction, delta):
        if interaction.user.id != self.owner_id:
            return await send_text(interaction.response.send_message, 'Open Community Rules from the dashboard to browse your own copy.', ephemeral=True)
        page = min(max(0, self.page + delta), len(rules_parts()) - 1)
        await interaction.response.edit_message(view=RulesPager(self.manager, self.owner_id, page),
                                                allowed_mentions=NO_MENTIONS)

    async def previous(self, interaction):
        await self.move(interaction, -1)

    async def next(self, interaction):
        await self.move(interaction, 1)


class DashboardManager:
    def __init__(self, bot, guild_id, tickets):
        self.bot, self.guild_id, self.tickets = bot, guild_id, tickets
        self.lock = asyncio.Lock()

    def register_view(self):
        self.bot.add_view(DashboardView(self))

    async def choose(self, interaction, value):
        if interaction.guild_id != self.guild_id:
            return await send_text(interaction.response.send_message, 'Use the dashboard in the Vynex server.', ephemeral=True)
        try:
            if value == 'rules':
                view = RulesPager(self, interaction.user.id)
            elif value == 'about':
                view = DashboardView(self, ABOUT)
            elif value == 'assistance':
                return await send_text(interaction.response.send_message, f'Support tickets have moved to <#{PANEL_CHANNEL_ID}>.', ephemeral=True)
            else:
                return await send_text(interaction.response.send_message, 'Choose an option from the dashboard menu.', ephemeral=True)
            await interaction.response.send_message(view=view, ephemeral=True, allowed_mentions=NO_MENTIONS)
        except (discord.HTTPException, RuntimeError):
            logging.exception('Dashboard selection failed.')
            send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await send_text(send, 'Unable to open that option. Please try again or contact staff.', ephemeral=True)

    async def ensure_dashboard(self):
        async with self.lock:
            channel = self.bot.get_channel(DASHBOARD_CHANNEL_ID) or await self.bot.fetch_channel(DASHBOARD_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
                raise RuntimeError('Dashboard channel must be a text channel in the configured server.')
            async for message in channel.history(limit=None, oldest_first=True):
                if message.author.id == self.bot.user.id and has_component(message, MENU_ID):
                    await publish_panel(channel, DashboardView(self), 'community', message=message)
                    return message
            return await publish_panel(channel, DashboardView(self), 'community')
