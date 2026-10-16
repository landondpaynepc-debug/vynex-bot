"""Persistent Components V2 purchase/support tickets and HTML transcripts."""
import asyncio
import html
import logging
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import discord

PANEL_CHANNEL_ID = 1542759018462715924
CATEGORY_ID = 1542810493792550962
TRANSCRIPT_CHANNEL_ID = 1542810514617536533
STAFF_ROLE_ID = 1542769771844599878
OPEN_ID = 'vynex:ticket:open:v2'
CLOSE_ID = 'vynex:ticket:close:v2'
KINDS = {'buy': 'Buy Tweaks', 'support': 'Support'}
TOPIC = re.compile(r'^vynex-ticket:v1;owner=(\d+);kind=(buy|support)$')
NO_MENTIONS = discord.AllowedMentions.none()
DESCRIPTION = '''# Vynex Tweaks — How to Purchase

Ready to get **Vynex Tweaks**? Follow these simple steps to purchase and get access.

**How to Buy:**
1. Open a purchase ticket.
2. Tell us which Vynex Tweaks package you want.
3. A staff member will provide the payment information.
4. Complete your payment through **PayPal**.
5. Send proof of payment in your ticket.
6. Once your payment is confirmed, you’ll receive your **Vynex Tweaks access/key** and instructions.

**Payment Method:** PayPal
Please only send payments using the information provided by an authorized Vynex Tweaks staff member.

**Vynex Tweaks — Optimize. Tweak. Perform.**

# Vynex Tweaks | Purchase Support
**Interested in purchasing Vynex Tweaks? Open a ticket below and our team will assist you with your purchase. Please have the following information ready:**
• The package/product you would like to purchase
• Your preferred payment method (PayPal)
• Any questions you have before purchasing

**Once your payment has been confirmed, a staff member will provide your Vynex Tweaks access/key along with any necessary setup instructions.**

⚠️ **Important:** Never send payment to anyone unless they are an authorized Vynex Tweaks staff member.

### Click below to open a Purchase Ticket and get started.'''


def ticket_info(channel):
    topic = getattr(channel, 'topic', '') or ''
    if not isinstance(topic, str):
        return None
    match = TOPIC.fullmatch(topic)
    if getattr(channel, 'category_id', None) != CATEGORY_ID or not match:
        return None
    return int(match[1]), match[2]


def safe_link(url):
    return html.escape(url, quote=True) if urlsplit(url).scheme in ('https', 'http') else ''


def has_component(message, custom_id):
    def contains(items):
        return any(item.get('custom_id') == custom_id or contains(item.get('components', [])) for item in items)
    return contains([component.to_dict() for component in message.components])


def message_html(message, attachment_links=None):
    author = html.escape(str(message.author))
    text = html.escape(message.content or '')
    extra = []
    for attachment in message.attachments:
        url = safe_link((attachment_links or {}).get(attachment.id, attachment.url))
        extra.append(f'<p>Attachment: <a href="{url}" rel="noreferrer">{html.escape(attachment.filename)}</a></p>')
    for embed in message.embeds:
        extra.append('<pre>' + html.escape(str(embed.to_dict())) + '</pre>')
    if getattr(message, 'components', None):
        extra.append('<pre>Components: ' + html.escape(str([item.to_dict() for item in message.components])) + '</pre>')
    return (f'<article><h3>{author} · {message.author.id} · {message.created_at.isoformat()}</h3>'
            f'<div class="body">{text}</div>{"".join(extra)}</article>\n').encode('utf-8')


async def write_transcripts(channel, directory, limit, attachment_links=None):
    """Split at message boundaries; never discard messages to meet upload limits."""
    header = ('<!doctype html><html><head><meta charset="utf-8">'
              '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
              '<title>Vynex ticket transcript</title><style>body{font-family:system-ui;margin:2em;background:transparent;color:inherit}'
              'article{border-bottom:1px solid #555;padding:1em 0}.body,pre{white-space:pre-wrap;overflow-wrap:anywhere}'
              'a{color:#b5a2ff}</style></head><body>'
              f'<h1>Ticket #{channel.id}: {html.escape(channel.name)}</h1>'
              '<p>Attachments are linked to their saved staff-archive messages when available. Staff Discord access is required.</p>\n').encode('utf-8')
    footer = b'</body></html>'
    parts, stream, size, count = [], None, 0, 0
    def new_part():
        name = Path(directory) / f'ticket-{channel.id}-part-{len(parts)+1}.html'
        parts.append(name)
        output = name.open('wb')
        output.write(header)
        return output, len(header)
    try:
        stream, size = new_part()
        async for message in channel.history(limit=None, oldest_first=True):
            entry = message_html(message, attachment_links)
            if len(header) + len(entry) + len(footer) > limit:
                raise RuntimeError('A transcript entry exceeds Discord’s upload limit. Ticket preserved for staff assistance.')
            if size + len(entry) + len(footer) > limit:
                stream.write(footer)
                stream.close()
                stream, size = new_part()
            stream.write(entry)
            size += len(entry)
            count += 1
        stream.write(footer)
    finally:
        if stream is not None:
            stream.close()
    return parts, count


class OpenSelect(discord.ui.Select):
    def __init__(self, manager):
        self.manager = manager
        super().__init__(custom_id=OPEN_ID, placeholder='Choose Buy Tweaks or Support',
                         options=[discord.SelectOption(label=label, value=value,
                                  emoji='🛒' if value == 'buy' else '🛠️') for value, label in KINDS.items()])

    async def callback(self, interaction):
        await self.manager.open_ticket(interaction, self.values[0])


class TicketPanel(discord.ui.LayoutView):
    def __init__(self, manager):
        super().__init__(timeout=None)
        self.add_item(discord.ui.TextDisplay(DESCRIPTION))
        self.add_item(discord.ui.Separator(visible=False))
        self.add_item(discord.ui.ActionRow(OpenSelect(manager)))


class CloseButton(discord.ui.Button):
    def __init__(self, manager):
        self.manager = manager
        super().__init__(label='Close Ticket', style=discord.ButtonStyle.secondary, custom_id=CLOSE_ID)

    async def callback(self, interaction):
        if not self.manager.authorized(interaction):
            return await interaction.response.send_message('Only this ticket’s owner or staff can close it.', ephemeral=True)
        await interaction.response.send_message(view=ConfirmClose(self.manager, interaction.user.id), ephemeral=True,
                                                allowed_mentions=NO_MENTIONS)


class TicketControls(discord.ui.LayoutView):
    def __init__(self, manager, welcome=None):
        super().__init__(timeout=None)
        children = [discord.ui.TextDisplay(welcome or '### Ticket controls\nClose your ticket when you are finished.')]
        children.append(discord.ui.ActionRow(CloseButton(manager)))
        for child in children:
            self.add_item(child)


class ConfirmClose(discord.ui.LayoutView):
    def __init__(self, manager, user_id):
        super().__init__(timeout=60)
        self.manager, self.user_id = manager, user_id
        button = discord.ui.Button(label='Save transcript & close', style=discord.ButtonStyle.secondary)
        button.callback = self.confirm
        self.add_item(discord.ui.TextDisplay('### Close this ticket?\nIts transcript will be saved to staff archives before this channel is deleted.'))
        self.add_item(discord.ui.ActionRow(button))

    async def confirm(self, interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message('This confirmation belongs to another user.', ephemeral=True)
        await self.manager.close_ticket(interaction)
        self.stop()


class TicketManager:
    def __init__(self, bot, guild_id, staff_role_id=STAFF_ROLE_ID):
        self.bot, self.guild_id, self.staff_role_id = bot, guild_id, staff_role_id
        self.open_lock, self.close_lock, self.panel_lock = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()

    def register_views(self):
        self.bot.add_view(TicketPanel(self))
        self.bot.add_view(TicketControls(self))

    def is_staff(self, member):
        perms = member.guild_permissions
        return perms.administrator or any(role.id == self.staff_role_id for role in member.roles)

    def authorized(self, interaction):
        return self.can_close(interaction.user, interaction.channel, interaction.guild_id)

    def can_close(self, user, channel, guild_id):
        info = ticket_info(channel)
        return (guild_id == self.guild_id and info is not None
                and (user.id == info[0] or self.is_staff(user)))

    async def resolve(self, channel_id, kind):
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, kind) or channel.guild.id != self.guild_id:
            raise RuntimeError(f'Ticket configuration: channel {channel_id} has the wrong type or server.')
        return channel

    async def ensure_panel(self):
        async with self.panel_lock:
            channel = await self.resolve(PANEL_CHANNEL_ID, discord.TextChannel)
            def ours(message):
                return message.author.id == self.bot.user.id and has_component(message, OPEN_ID)
            existing = None
            async for message in channel.pins(limit=100):
                if ours(message): existing = message; break
            if existing is None:
                async for message in channel.history(limit=100):
                    if ours(message): existing = message; break
            view = TicketPanel(self)
            if existing:
                await existing.edit(view=view, allowed_mentions=NO_MENTIONS)
                return existing
            message = await channel.send(view=view, allowed_mentions=NO_MENTIONS)
            try:
                await message.pin(reason='Persistent Vynex ticket panel')
            except discord.Forbidden:
                logging.warning('Ticket panel posted; Manage Messages permission is needed to pin it.')
            return message

    def welcome_text(self, owner_id, kind):
        text = ('Tell staff which package you want, confirm PayPal as your payment method, and ask any purchase questions.'
                if kind == 'buy' else 'Describe the problem, the app you are using, and any error messages or screenshots.')
        return f'## {KINDS[kind]}\n<@{owner_id}>, welcome!\nStaff: <@&{self.staff_role_id}>\n{text}\n\nStaff will assist you here.'

    async def refresh_open_tickets(self):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return
        for channel in await guild.fetch_channels():
            info = ticket_info(channel)
            if info is None:
                continue
            try:
                async for message in channel.history(limit=20, oldest_first=True):
                    if message.author.id == self.bot.user.id and has_component(message, CLOSE_ID):
                        await message.edit(view=TicketControls(self, self.welcome_text(*info)), allowed_mentions=NO_MENTIONS)
                        break
            except discord.HTTPException:
                logging.warning('Unable to refresh existing ticket controls in channel %s.', channel.id)

    async def open_ticket(self, interaction, kind):
        if interaction.guild_id != self.guild_id or kind not in KINDS:
            return await interaction.response.send_message('Use the ticket panel in the Vynex server.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            async with self.open_lock:
                category = await self.resolve(CATEGORY_ID, discord.CategoryChannel)
                await self.resolve(TRANSCRIPT_CHANNEL_ID, discord.TextChannel)
                channels = await interaction.guild.fetch_channels()
                existing = next((c for c in channels if ticket_info(c) == (interaction.user.id, kind)), None)
                if existing:
                    return await interaction.followup.send(f'Your existing ticket: {existing.mention}', ephemeral=True)
                member = interaction.user
                me = interaction.guild.me
                if not any(role.id == self.staff_role_id for role in interaction.guild.roles):
                    raise RuntimeError('Configured ticket staff role is missing from the server.')
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                        attach_files=True, embed_links=True),
                    me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                    manage_channels=True, attach_files=True, embed_links=True),
                }
                for role in interaction.guild.roles:
                    if role != interaction.guild.default_role and role.id == self.staff_role_id:
                        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                                      attach_files=True, embed_links=True)
                channel = await interaction.guild.create_text_channel(
                    name=f'{"buy-tweaks" if kind == "buy" else "support"}-{member.id}', category=category,
                    overwrites=overwrites, topic=f'vynex-ticket:v1;owner={member.id};kind={kind}',
                    reason=f'Vynex {KINDS[kind]} ticket opened by {member.id}')
                await channel.send(view=TicketControls(self, self.welcome_text(member.id, kind)),
                                   allowed_mentions=discord.AllowedMentions(everyone=False, users=[member],
                                       roles=[discord.Object(id=self.staff_role_id)], replied_user=False))
                await interaction.followup.send(f'Your private ticket is ready: {channel.mention}', ephemeral=True)
        except (discord.HTTPException, RuntimeError) as error:
            logging.error('Ticket creation failed: %s', type(error).__name__)
            await interaction.followup.send('Unable to open a ticket. Staff: check the configured category, staff role and bot channel permissions.', ephemeral=True)

    async def close_ticket(self, interaction):
        if not self.authorized(interaction):
            return await interaction.response.send_message('Only this ticket’s owner or staff can close it.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with self.close_lock:
            channel, original_overwrites = None, None
            try:
                channel = await interaction.guild.fetch_channel(interaction.channel_id)
                if not self.can_close(interaction.user, channel, interaction.guild_id):
                    return await interaction.followup.send('This is not an active Vynex ticket.', ephemeral=True)
                archive = await self.resolve(TRANSCRIPT_CHANNEL_ID, discord.TextChannel)
                if not self.bot.intents.message_content:
                    raise RuntimeError('Message Content Intent is required for complete transcripts.')
                original_overwrites = channel.overwrites
                frozen = {}
                for target, value in original_overwrites.items():
                    updated = discord.PermissionOverwrite.from_pair(*value.pair())
                    if target.id != self.bot.user.id and value.view_channel is True:
                        updated.send_messages = False
                    frozen[target] = updated
                await channel.edit(overwrites=frozen, reason='Freeze Vynex ticket during transcript export')
                await channel.send('Closing this ticket and saving its transcript. Please stop sending messages.', allowed_mentions=NO_MENTIONS)
                with tempfile.TemporaryDirectory(prefix='vynex-transcript-') as directory:
                    limit = min(interaction.guild.filesize_limit - 1024, 8 * 1024 * 1024)
                    attachment_links = {}
                    async for message in channel.history(limit=None, oldest_first=True):
                        for attachment in message.attachments:
                            if attachment.size > limit:
                                raise RuntimeError('An attachment exceeds the archive upload limit. Ticket preserved.')
                            local_file = Path(directory) / f'attachment-{attachment.id}'
                            await attachment.save(local_file)
                            if local_file.stat().st_size > limit:
                                raise RuntimeError('Attachment exceeded the archive upload limit. Ticket preserved.')
                            filename = f'{attachment.id}-' + re.sub(r'[^A-Za-z0-9._-]', '_', attachment.filename)[-120:]
                            file = discord.File(local_file, filename=filename)
                            try:
                                view = discord.ui.LayoutView(timeout=None)
                                view.add_item(discord.ui.TextDisplay(f'### Ticket attachment\nTicket: {channel.id} · Message: {message.id}\nAuthor: {message.author.id}'))
                                view.add_item(discord.ui.File(f'attachment://{filename}'))
                                saved = await archive.send(file=file, view=view, allowed_mentions=NO_MENTIONS)
                                attachment_links[attachment.id] = saved.jump_url
                            finally:
                                file.close()
                    parts, count = await write_transcripts(channel, directory, limit, attachment_links)
                    info = ticket_info(channel)
                    for index, part in enumerate(parts, 1):
                        file = discord.File(part, filename=part.name)
                        try:
                            view = discord.ui.LayoutView(timeout=None)
                            view.add_item(discord.ui.TextDisplay(f'## Ticket transcript\nTicket: {channel.id} · {KINDS[info[1]]}\nOwner: {info[0]}\nClosed by: {interaction.user.id}\nMessages: {count} · Part {index}/{len(parts)}'))
                            view.add_item(discord.ui.File(f'attachment://{part.name}'))
                            await archive.send(file=file, view=view, allowed_mentions=NO_MENTIONS)
                        finally:
                            file.close()
                await interaction.followup.send('Transcript saved to the staff archive. Closing the ticket now.', ephemeral=True)
                await channel.delete(reason=f'Vynex ticket closed by {interaction.user.id}; transcript archived to {TRANSCRIPT_CHANNEL_ID}')
            except discord.NotFound:
                await interaction.followup.send('The ticket channel is already closed or a configured channel is missing.', ephemeral=True)
            except (discord.HTTPException, RuntimeError, OSError) as error:
                if channel is not None and original_overwrites is not None:
                    try:
                        await channel.edit(overwrites=original_overwrites, reason='Reopen Vynex ticket after archive failure')
                    except discord.HTTPException:
                        logging.error('Could not restore ticket send permissions after archive failure.')
                logging.error('Ticket archive/close failed: %s', type(error).__name__)
                await interaction.followup.send('Ticket kept open: transcript saving or channel cleanup failed. Staff should check Message Content Intent, Read Message History and archive permissions.', ephemeral=True)
