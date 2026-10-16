import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from tickets import (TicketManager, TicketPanel, TicketControls, DESCRIPTION, CATEGORY_ID,
                     PANEL_CHANNEL_ID, TRANSCRIPT_CHANNEL_ID, OPEN_ID, write_transcripts)


async def stream(values):
    for value in values:
        yield value


def fixture():
    everyone = MagicMock(spec=discord.Role); everyone.id = 1
    everyone.permissions = NS(manage_channels=False)
    staff = MagicMock(spec=discord.Role); staff.id = 77
    staff.permissions = NS(manage_channels=False)
    owner = MagicMock(spec=discord.Member); owner.id = 42
    owner.roles = []; owner.guild_permissions = NS(administrator=False, manage_channels=False)
    me = MagicMock(spec=discord.Member); me.id = 99
    guild = MagicMock(spec=discord.Guild)
    guild.id = 10; guild.me = me; guild.default_role = everyone; guild.roles = [everyone, staff]
    guild.filesize_limit = 10 * 1024 * 1024
    category = MagicMock(spec=discord.CategoryChannel); category.id = CATEGORY_ID; category.guild = guild
    archive = MagicMock(spec=discord.TextChannel); archive.id = TRANSCRIPT_CHANNEL_ID; archive.guild = guild
    archive.send = AsyncMock()
    panel = MagicMock(spec=discord.TextChannel); panel.id = PANEL_CHANNEL_ID; panel.guild = guild
    panel.send = AsyncMock()
    channels = []
    guild.fetch_channels = AsyncMock(return_value=channels)
    async def create(**kwargs):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 555; channel.name = kwargs['name']; channel.topic = kwargs['topic']
        channel.category_id = CATEGORY_ID; channel.mention = '<#555>'; channel.guild = guild
        channel.overwrites = kwargs['overwrites']
        channel.send = AsyncMock(); channel.edit = AsyncMock(); channel.delete = AsyncMock()
        channels.append(channel)
        return channel
    guild.create_text_channel = AsyncMock(side_effect=create)
    known = {CATEGORY_ID:category, TRANSCRIPT_CHANNEL_ID:archive, PANEL_CHANNEL_ID:panel}
    intents = discord.Intents.default(); intents.message_content = True
    bot = NS(user=me, intents=intents, get_channel=known.get, fetch_channel=AsyncMock(), add_view=MagicMock())
    manager = TicketManager(bot, guild.id, staff.id)
    def interaction(channel=panel, user=owner):
        return NS(guild=guild, guild_id=guild.id, channel=channel, channel_id=channel.id, user=user,
                  response=NS(defer=AsyncMock(), send_message=AsyncMock()), followup=NS(send=AsyncMock()))
    return NS(manager=manager, bot=bot, guild=guild, owner=owner, me=me, everyone=everyone, staff=staff,
              panel=panel, archive=archive, channels=channels, interaction=interaction, category=category)


class TicketTests(unittest.IsolatedAsyncioTestCase):
    async def test_components_v2_are_persistent_and_have_both_choices(self):
        f = fixture()
        panel = TicketPanel(f.manager)
        self.assertIsInstance(panel, discord.ui.LayoutView)
        self.assertTrue(panel.is_persistent())
        self.assertEqual(panel.to_components()[0]['type'], 10)
        self.assertNotIn(17, [item['type'] for item in panel.to_components()])
        select = panel.to_components()[-1]['components'][0]
        self.assertEqual(select['custom_id'], OPEN_ID)
        self.assertEqual([o['label'] for o in select['options']], ['Buy Tweaks', 'Support'])
        self.assertIn('PayPal', DESCRIPTION)
        self.assertIn('Never send payment', DESCRIPTION)
        self.assertTrue(TicketControls(f.manager).is_persistent())
        f.manager.register_views()
        self.assertEqual(f.bot.add_view.call_count, 2)

    async def test_private_category_ticket_and_duplicate_prevention(self):
        f = fixture()
        await asyncio.gather(f.manager.open_ticket(f.interaction(), 'buy'),
                             f.manager.open_ticket(f.interaction(), 'buy'))
        self.assertEqual(f.guild.create_text_channel.call_count, 1)
        request = f.guild.create_text_channel.call_args.kwargs
        self.assertIs(request['category'], f.category)
        self.assertFalse(request['overwrites'][f.everyone].view_channel)
        self.assertTrue(request['overwrites'][f.owner].view_channel)
        self.assertTrue(request['overwrites'][f.staff].view_channel)
        welcome = f.channels[0].send.call_args.kwargs
        mentions = welcome['allowed_mentions'].to_dict()
        self.assertEqual(mentions['users'], [42])
        self.assertEqual(mentions['roles'], [77])
        self.assertNotIn('everyone', mentions['parse'])
        text = welcome['view'].to_components()[0]['content']
        self.assertIn('<@42>', text)
        self.assertIn('<@&77>', text)
        await f.manager.open_ticket(f.interaction(), 'support')
        self.assertEqual(f.guild.create_text_channel.call_count, 2)
        self.assertIn('kind=support', f.channels[-1].topic)

    async def test_panel_refresh_edits_existing_pinned_panel(self):
        f = fixture()
        original = NS(author=f.me, components=[NS(to_dict=lambda value=value: value) for value in TicketPanel(f.manager).to_components()], edit=AsyncMock())
        f.panel.pins = lambda **kw: stream([original])
        f.panel.history = lambda **kw: stream([])
        await f.manager.ensure_panel()
        await f.manager.ensure_panel()
        self.assertEqual(original.edit.call_count, 2)
        f.panel.send.assert_not_called()

    async def test_transcript_escapes_html_and_splits_without_dropping_messages(self):
        message = NS(author=NS(id=42), content='<script>alert("x")</script>' * 5,
                     created_at=datetime.now(timezone.utc), attachments=[], embeds=[], components=[])
        channel = NS(id=555, name='<unsafe>', history=lambda **kw: stream([message] * 5))
        with tempfile.TemporaryDirectory() as directory:
            parts, count = await write_transcripts(channel, directory, 1700)
            self.assertEqual(count, 5)
            self.assertGreater(len(parts), 1)
            text = ''.join(part.read_text(encoding='utf-8') for part in parts)
            self.assertNotIn('<script>', text)
            self.assertIn('&lt;script&gt;', text)
            self.assertTrue(all(part.stat().st_size <= 1700 for part in parts))

    async def test_archive_saved_before_delete_and_failure_preserves_ticket(self):
        for fail in (False, True):
            f = fixture()
            await f.manager.open_ticket(f.interaction(), 'support')
            channel = f.channels[0]
            f.guild.fetch_channel = AsyncMock(return_value=channel)
            channel.history = lambda **kw: stream([NS(author=f.owner, content='Test transcript',
                created_at=datetime.now(timezone.utc), attachments=[], embeds=[], components=[])])
            events = []
            async def save(**kw):
                if fail: raise OSError('simulated upload failure')
                self.assertIn(b'Test transcript', kw['file'].fp.read())
                self.assertIsInstance(kw['view'], discord.ui.LayoutView)
                events.append('archive')
            async def delete(**kw): events.append('delete')
            f.archive.send.side_effect = save
            channel.delete.side_effect = delete
            await f.manager.close_ticket(f.interaction(channel))
            self.assertEqual(events, [] if fail else ['archive', 'delete'])
            if fail:
                channel.delete.assert_not_called()
                self.assertEqual(channel.edit.call_count, 2)

    async def test_unrelated_user_cannot_close_and_wrong_channel_is_rejected(self):
        f = fixture()
        await f.manager.open_ticket(f.interaction(), 'buy')
        stranger = NS(id=123, roles=[], guild_permissions=NS(administrator=False, manage_channels=False))
        interaction = f.interaction(f.channels[0], stranger)
        await f.manager.close_ticket(interaction)
        interaction.response.defer.assert_not_called()
        f.channels[0].delete.assert_not_called()
        self.assertFalse(f.manager.can_close(f.owner, f.panel, f.guild.id))

    async def test_named_staff_role_has_close_access(self):
        f = fixture()
        self.assertEqual(TicketManager(f.bot, f.guild.id).staff_role_id, 1542769771844599878)
        await f.manager.open_ticket(f.interaction(), 'buy')
        staff = NS(id=567, roles=[f.staff], guild_permissions=NS(administrator=False, manage_channels=False))
        self.assertTrue(f.manager.can_close(staff, f.channels[0], f.guild.id))

    async def test_ticket_controls_have_no_container_accents_or_red_buttons(self):
        from tickets import ConfirmClose
        f = fixture()
        for view in (TicketPanel(f.manager), TicketControls(f.manager), ConfirmClose(f.manager, 42)):
            def check(items):
                for item in items:
                    self.assertNotEqual(item['type'], 17)
                    self.assertNotIn('accent_color', item)
                    if item['type'] == 2:
                        self.assertEqual(item['style'], discord.ButtonStyle.secondary.value)
                    check(item.get('components', []))
            check(view.to_components())

    async def test_existing_ticket_refresh_has_no_repeat_pings(self):
        f = fixture()
        await f.manager.open_ticket(f.interaction(), 'support')
        channel = f.channels[0]
        control = TicketControls(f.manager).to_components()
        message = NS(author=f.me, components=[NS(to_dict=lambda value=value: value) for value in control], edit=AsyncMock())
        channel.history = lambda **kw: stream([message])
        f.bot.get_guild = lambda guild_id: f.guild
        await f.manager.refresh_open_tickets()
        message.edit.assert_awaited_once()
        request = message.edit.call_args.kwargs
        self.assertEqual(request['allowed_mentions'].to_dict()['parse'], [])
        self.assertTrue(all(item['type'] != 17 for item in request['view'].to_components()))

    async def test_attachment_saved_and_linked_in_transcript_before_delete(self):
        f = fixture()
        await f.manager.open_ticket(f.interaction(), 'support')
        channel = f.channels[0]
        f.guild.fetch_channel = AsyncMock(return_value=channel)
        async def save(path): Path(path).write_bytes(b'payment-proof-fixture')
        attachment = NS(id=999, filename='proof.txt', size=21, url='https://example.invalid/original', save=save)
        message = NS(id=1234, author=f.owner, content='Payment proof', created_at=datetime.now(timezone.utc),
                     attachments=[attachment], embeds=[], components=[])
        channel.history = lambda **kw: stream([message])
        events = []
        async def archive(**kw):
            data = kw['file'].fp.read()
            if kw['file'].filename.endswith('.html'):
                self.assertIn(b'https://discord.com/channels/10/20/30', data)
                self.assertNotIn(b'https://example.invalid/original', data)
                events.append('transcript')
            else:
                self.assertEqual(data, b'payment-proof-fixture')
                events.append('attachment')
            return NS(jump_url='https://discord.com/channels/10/20/30')
        f.archive.send.side_effect = archive
        async def delete(**kw): events.append('delete')
        channel.delete.side_effect = delete
        await f.manager.close_ticket(f.interaction(channel))
        self.assertEqual(events, ['attachment','transcript','delete'])


if __name__ == '__main__': unittest.main(verbosity=2)
