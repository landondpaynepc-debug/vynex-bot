"""Components V2 welcome messages for new server members."""
import logging

import discord

from ui_messages import TICKET_COLOR

WELCOME_CHANNEL_ID = 1542758858886225930
AUTO_ROLE_ID = 1542769773882908743


class WelcomeView(discord.ui.LayoutView):
    def __init__(self, member):
        super().__init__(timeout=None)
        count = member.guild.member_count
        count_text = f'We now have **{count:,} members**.' if count is not None else 'We’re glad you’re here.'
        self.add_item(discord.ui.Container(
            discord.ui.Section(
                discord.ui.TextDisplay('# Welcome to Vynex Tweaks'),
                discord.ui.TextDisplay(f'<@{member.id}>, welcome! {count_text} Read the rules and get chatting.'),
                accessory=discord.ui.Thumbnail(str(member.display_avatar.url))),
            discord.ui.Separator(),
            discord.ui.TextDisplay('## WELCOME TO VYNEX TWEAKS!\n'
                'Read the rules, meet the community, and make yourself at home.\n\n'
                '**Optimize. Refine. Perform.**'),
            discord.ui.TextDisplay('-# Vynex Tweaks • Welcomer'), accent_colour=TICKET_COLOR))


class WelcomeManager:
    def __init__(self, bot, guild_id):
        self.bot, self.guild_id = bot, guild_id

    async def channel(self):
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID) or await self.bot.fetch_channel(WELCOME_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise RuntimeError('Welcome channel must be a text channel in the configured server.')
        return channel

    async def check(self):
        await self.channel()

    async def auto_role(self, guild):
        role = guild.get_role(AUTO_ROLE_ID)
        if role is None:
            role = next((role for role in await guild.fetch_roles() if role.id == AUTO_ROLE_ID), None)
        if role is None:
            raise RuntimeError('Configured auto role is missing.')
        me = guild.me or await guild.fetch_member(self.bot.user.id)
        if not me.guild_permissions.manage_roles:
            raise RuntimeError('Bot needs Manage Roles for automatic role assignment.')
        if role.managed or role.is_default() or role >= me.top_role:
            raise RuntimeError('Auto role must be assignable and below the bot’s highest role.')
        return role

    async def check_auto_role(self):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise RuntimeError('Configured server is unavailable for auto-role checks.')
        await self.auto_role(guild)

    async def assign_role(self, member):
        if member.guild.id != self.guild_id:
            return False
        if any(role.id == AUTO_ROLE_ID for role in member.roles):
            return True
        try:
            role = await self.auto_role(member.guild)
            await member.add_roles(role, reason='Vynex automatic role for new server member', atomic=True)
            return True
        except (discord.HTTPException, RuntimeError) as error:
            logging.error('Auto-role assignment failed for member %s: %s. Check Manage Roles and role hierarchy.',
                          member.id, str(error) if isinstance(error, RuntimeError) else type(error).__name__)
            return False

    async def joined(self, member):
        if member.guild.id != self.guild_id:
            return False
        try:
            channel = await self.channel()
            await channel.send(view=WelcomeView(member), allowed_mentions=discord.AllowedMentions(
                everyone=False, users=[member], roles=False, replied_user=False))
            return True
        except (discord.HTTPException, RuntimeError) as error:
            logging.error('Welcome delivery failed (%s). Check welcome channel permissions.', type(error).__name__)
            return False
