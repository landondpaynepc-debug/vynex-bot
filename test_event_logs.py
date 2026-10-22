import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from event_logs import EventLogs, LOG_CHANNEL_ID
from tickets import TICKET_COLOR


def fixture():
    channel = MagicMock(spec=discord.TextChannel)
    channel.guild = NS(id=10, me=NS())
    channel.permissions_for.return_value = NS(view_channel=True, send_messages=True)
    channel.send = AsyncMock()
    bot = NS(user=NS(id=99), get_channel=lambda ident: channel, get_guild=lambda ident: None)
    return EventLogs(bot, 10), channel


class LogTests(unittest.IsolatedAsyncioTestCase):
    async def test_key_logs_include_actor_full_key_and_app_without_pings(self):
        logs, channel = fixture()
        interaction = NS(user=NS(id=42), channel_id=123, id=456)
        self.assertTrue(await logs.key_generated(interaction, 'Vynex Tweaks', 'VYNEX-TEST-1234'))
        request = channel.send.call_args.kwargs
        root = request['view'].to_components()[0]
        self.assertEqual(root['type'], 17)
        self.assertEqual(root['accent_color'], TICKET_COLOR)
        text = root['components'][0]['content']
        for value in ('42', 'Vynex Tweaks', 'VYNEX-TEST-1234'):
            self.assertIn(value, text)
        self.assertEqual(request['allowed_mentions'].to_dict()['parse'], [])

    async def test_delivery_failure_does_not_expose_key(self):
        logs, channel = fixture()
        channel.permissions_for.return_value.send_messages = False
        with patch('event_logs.logging.error') as error:
            self.assertFalse(await logs.key_generated(NS(user=NS(id=42), channel_id=1, id=2), 'premium', 'SECRET-KEY'))
        self.assertNotIn('SECRET-KEY', str(error.call_args))
        channel.send.assert_not_called()

    async def test_missing_cached_bot_member_is_resolved(self):
        logs, channel = fixture()
        channel.guild.me = None
        channel.guild.fetch_member = AsyncMock(return_value=NS(id=99))
        self.assertTrue(await logs.send('Test', 'Test event'))
        channel.guild.fetch_member.assert_awaited_once_with(99)

    async def test_unexpected_error_reports_type_without_secret_body(self):
        logs, channel = fixture()
        channel.send.side_effect = ValueError('SECRET-KEY')
        with patch('event_logs.logging.error') as error:
            self.assertFalse(await logs.send('Key', 'SECRET-KEY'))
        self.assertIn('ValueError', logs.last_error)
        self.assertNotIn('SECRET-KEY', logs.last_error)
        self.assertNotIn('SECRET-KEY', str(error.call_args))

    async def test_cached_uncached_bulk_and_log_channel_deletions(self):
        logs, channel = fixture()
        message = NS(id=7, author=NS(id=42), content='deleted text', attachments=[], embeds=[], components=[])
        await logs.deleted(NS(guild_id=10, channel_id=5, message_id=7, cached_message=message))
        self.assertIn('deleted text', channel.send.call_args.kwargs['view'].to_components()[0]['components'][0]['content'])
        await logs.deleted(NS(guild_id=10, channel_id=5, message_ids={7, 8}, cached_messages=[message]))
        self.assertIn('not in the bot cache', channel.send.call_args.kwargs['view'].to_components()[0]['components'][0]['content'])
        self.assertEqual(channel.send.await_count, 3)
        await logs.deleted(NS(guild_id=10, channel_id=LOG_CHANNEL_ID))
        await logs.deleted(NS(guild_id=11, channel_id=5))
        self.assertEqual(channel.send.await_count, 3)

    async def test_moderation_command_and_external_audit(self):
        logs, channel = fixture()
        await logs.command_completed(NS(guild_id=10, user=NS(id=42), channel_id=5,
            namespace=[('member', NS(id=123)), ('reason', 'Spam')]), NS(name='ban'))
        text = channel.send.call_args.kwargs['view'].to_components()[0]['components'][0]['content']
        self.assertIn('Moderator:', text)
        self.assertIn('Spam', text)
        entry = NS(action=NS(name='ban'), guild=NS(id=10), user_id=42, user='Staff', target=NS(id=123), reason='Spam', id=456)
        await logs.audit_entry(entry)
        self.assertEqual(channel.send.await_count, 2)
        entry.user_id = 99
        await logs.audit_entry(entry)
        self.assertEqual(channel.send.await_count, 2)

    async def test_long_messages_stay_within_discord_limit(self):
        logs, channel = fixture()
        await logs.send('Message deleted', 'x' * 9000)
        self.assertEqual(channel.send.await_count, 3)
        for call in channel.send.call_args_list:
            root = call.kwargs['view'].to_components()[0]
            self.assertLessEqual(sum(len(c.get('content', '')) for c in root['components']), 4000)
