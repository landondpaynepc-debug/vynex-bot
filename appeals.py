"""DM ban appeals, with persistent buttons and Discord-backed duplicate checks."""
import asyncio
from datetime import timedelta
import logging
import re
import secrets

import discord
from ui_messages import TICKET_COLOR, send_text

APPEAL_CHANNEL_ID = 1542759018462715924
NO_MENTIONS = discord.AllowedMentions.none()
CASE_PATTERN = r'vynex:appeal:v1:(?P<guild>\d{1,20}):(?P<user>\d{1,20}):(?P<case>[a-f0-9]{24})'
QUESTIONS = (
    ('What happened before you were banned?', True),
    ('Why should your ban be reconsidered?', True),
    ('What will you do differently if unbanned?', True),
    ('Anything else staff should know?', False),
)


class AppealButton(discord.ui.DynamicItem[discord.ui.Button], template=CASE_PATTERN):
    def __init__(self, guild_id, user_id, case_id):
        self.guild_id, self.user_id, self.case_id = guild_id, user_id, case_id
        super().__init__(discord.ui.Button(
            label='Submit a ban appeal', style=discord.ButtonStyle.secondary,
            custom_id=f'vynex:appeal:v1:{guild_id}:{user_id}:{case_id}'))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match['guild']), int(match['user']), match['case'])

    async def callback(self, interaction):
        await interaction.client.appeals.open_form(interaction, self.guild_id, self.user_id, self.case_id)


def invitation_view(guild, user_id, case_id, before_ban=False):
    view = discord.ui.LayoutView(timeout=None)
    name = discord.utils.escape_markdown(guild.name)
    notice = (f'A moderator has requested a ban for you in **{name}**. '
              'This form can be submitted only if the ban is applied.' if before_ban else
              f'You have been banned from **{name}**.')
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay('# Ban appeal\n' + notice + '\n\n'
            'You can explain what happened, why the ban should be reconsidered, '
            'and what you would do differently. Your Discord account and answers will be '
            'sent to the server’s appeal channel for review. Submitting does not automatically unban you.\n\n'
            'Select the button below to open the questionnaire.'),
        discord.ui.ActionRow(AppealButton(guild.id, user_id, case_id)), accent_colour=TICKET_COLOR))
    return view


class AppealModal(discord.ui.Modal):
    def __init__(self, manager, user_id, case_id, issued_at):
        super().__init__(title='Vynex ban appeal', timeout=900)
        self.manager, self.user_id, self.case_id, self.issued_at = manager, user_id, case_id, issued_at
        self.answers = []
        for index, (label, required) in enumerate(QUESTIONS):
            field = discord.ui.TextInput(label=label, custom_id=f'answer-{index}',
                style=discord.TextStyle.paragraph, required=required,
                min_length=10 if required else None, max_length=1000)
            self.answers.append(field)
            self.add_item(field)

    async def on_submit(self, interaction):
        await self.manager.submit(interaction, self.user_id, self.case_id, self.issued_at,
                                  [str(field.value).strip() for field in self.answers])

    async def on_error(self, interaction, error):
        logging.error('Ban appeal handler failed (%s).', type(error).__name__)
        sender = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send_text(sender, 'The appeal result could not be confirmed. Reopen the questionnaire to try again; '
                        'the bot checks for an existing submission before sending another.', ephemeral=True)


class AppealManager:
    def __init__(self, bot, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.notice_lock, self.submit_lock = asyncio.Lock(), asyncio.Lock()
        self.notices = {}

    def register_view(self):
        self.bot.add_dynamic_items(AppealButton)

    async def channel(self):
        channel = self.bot.get_channel(APPEAL_CHANNEL_ID) or await self.bot.fetch_channel(APPEAL_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise RuntimeError('The appeal destination must be a text channel in the configured server.')
        permissions = channel.permissions_for(channel.guild.me)
        if not all((permissions.view_channel, permissions.send_messages, permissions.embed_links,
                    permissions.read_message_history)):
            raise RuntimeError('Appeals need View Channel, Send Messages, Embed Links and Read Message History.')
        return channel

    async def check(self):
        await self.channel()
        guild = self.bot.get_guild(self.guild_id)
        if guild is None or not guild.me.guild_permissions.ban_members:
            raise RuntimeError('Ban Members permission is needed to verify appeal eligibility.')

    def forget(self, guild, user):
        if guild.id == self.guild_id:
            self.notices.pop(user.id, None)

    async def notify_ban(self, guild, user, *, before_ban=False):
        if guild.id != self.guild_id or user.bot:
            return False
        async with self.notice_lock:
            # A pre-ban invitation and the resulting gateway event share one notice.
            if user.id in self.notices:
                return self.notices[user.id]['delivered']
            case_id = secrets.token_hex(12)
            record = {'case': case_id, 'delivered': False}
            self.notices[user.id] = record
            try:
                await asyncio.wait_for(user.send(view=invitation_view(guild, user.id, case_id, before_ban),
                                                  allowed_mentions=NO_MENTIONS), timeout=8)
                record['delivered'] = True
                return True
            except (discord.HTTPException, TimeoutError, OSError) as error:
                logging.warning('Ban appeal DM could not be confirmed (%s).', type(error).__name__)
        # DM failure never cancels or delays the ban indefinitely.
        try:
            await asyncio.wait_for(self.bot.event_logs.send('Ban appeal DM unavailable',
                f'User ID: {user.id}\nThe appeal invitation could not be delivered or confirmed. '
                'Discord may block DMs after removal, or the member may have closed DMs. '
                'No automatic unban was performed.'), timeout=8)
        except (discord.HTTPException, TimeoutError, OSError):
            logging.warning('Could not deliver the ban-appeal DM failure notice to staff.')
        return False

    async def open_form(self, interaction, guild_id, user_id, case_id):
        # No network request before the modal: Discord requires a prompt initial reply.
        message = interaction.message
        if (guild_id != self.guild_id or interaction.guild_id is not None or interaction.user.id != user_id
                or message is None or message.author.id != self.bot.user.id
                or not re.fullmatch(r'[a-f0-9]{24}', case_id)):
            return await send_text(interaction.response.send_message,
                'This appeal invitation belongs to another user or server.', ephemeral=True)
        await interaction.response.send_modal(AppealModal(self, user_id, case_id, message.created_at))

    async def submit(self, interaction, user_id, case_id, issued_at, answers):
        if interaction.guild_id is not None or interaction.user.id != user_id:
            return await send_text(interaction.response.send_message,
                                   'This questionnaire belongs to another user.', ephemeral=True)
        if (len(answers) != len(QUESTIONS) or any(not isinstance(a, str) or len(a) > 1000 or
                (required and len(a.strip()) < 10) for a, (_, required) in zip(answers, QUESTIONS))):
            return await send_text(interaction.response.send_message,
                'Please answer all required questions with at least 10 characters (maximum 1,000 each).', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.submit_lock:
                guild = self.bot.get_guild(self.guild_id)
                if guild is None:
                    raise RuntimeError('Server unavailable.')
                try:
                    await guild.fetch_ban(discord.Object(id=user_id))
                except discord.NotFound:
                    return await send_text(interaction.followup.send,
                        'You are not currently banned from this server. No appeal was sent.', ephemeral=True)
                channel = await self.channel()
                prefix = f'vynex-appeal:v1:{self.guild_id}:{user_id}:'
                # Discord messages remain authoritative across restarts and Render deploys.
                # A newer appeal also prevents an older invitation from creating another.
                async for message in channel.history(limit=None, after=issued_at-timedelta(seconds=5), oldest_first=False):
                    if message.author.id == self.bot.user.id and any(
                            str(embed.footer.text or '').startswith(prefix) for embed in message.embeds):
                        return await send_text(interaction.followup.send,
                            'Your appeal has already been submitted. Please wait for staff to review it.', ephemeral=True)
                embed = discord.Embed(title='Ban appeal · awaiting staff review', colour=TICKET_COLOR,
                    description=f'Account: {discord.utils.escape_markdown(str(interaction.user))[:200]}\nUser ID: `{user_id}`',
                    timestamp=discord.utils.utcnow())
                for (question, _), answer in zip(QUESTIONS, answers):
                    embed.add_field(name=question, value=answer.strip() or 'No additional information.', inline=False)
                embed.set_footer(text=prefix+case_id)
                await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
            await send_text(interaction.followup.send,
                'Your ban appeal was submitted to the server’s appeal channel. Staff will review it; '
                'your ban remains in place unless they decide to remove it.', ephemeral=True)
        except (discord.HTTPException, RuntimeError, TimeoutError, OSError) as error:
            # Never log the questionnaire or Discord response body.
            logging.error('Ban appeal submission could not be confirmed (%s).', type(error).__name__)
            await send_text(interaction.followup.send,
                'Your appeal could not be confirmed. Please reopen the questionnaire and try again. '
                'The bot checks for an existing submission before sending another.', ephemeral=True)
