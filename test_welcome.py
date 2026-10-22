import ast
from pathlib import Path
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord
from welcome import WelcomeManager, WelcomeView, WELCOME_CHANNEL_ID
from ui_messages import TICKET_COLOR, send_text


class WelcomeTests(unittest.IsolatedAsyncioTestCase):
    def member(self, guild=10):
        return NS(id=42, guild=NS(id=guild, member_count=1626),
                  display_avatar=NS(url='https://cdn.discordapp.com/embed/avatars/0.png'))

    async def test_welcome_uses_avatar_count_v2_and_no_channel_list(self):
        root = WelcomeView(self.member()).to_components()[0]
        self.assertEqual(root['type'], 17)
        self.assertEqual(root['accent_color'], TICKET_COLOR)
        section = root['components'][0]
        self.assertEqual(section['type'], 9)
        self.assertEqual(section['accessory']['type'], 11)
        text = str(root)
        self.assertIn('1,626', text)
        self.assertIn('<@42>', text)
        self.assertIn('Welcome to Vynex Tweaks', text)
        self.assertNotIn('following channels', text)
        self.assertNotIn('<#', text)

    async def test_only_target_server_and_joiner_are_notified(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = NS(id=10)
        channel.send = AsyncMock()
        manager = WelcomeManager(NS(get_channel=lambda ident: channel if ident == WELCOME_CHANNEL_ID else None), 10)
        self.assertFalse(await manager.joined(self.member(20)))
        self.assertTrue(await manager.joined(self.member()))
        channel.send.assert_awaited_once()
        request = channel.send.call_args.kwargs
        self.assertTrue(request['view'].has_components_v2())
        mentions = request['allowed_mentions'].to_dict()
        self.assertEqual(mentions['users'], [42])
        self.assertEqual(mentions['parse'], [])

    async def test_all_text_replies_use_size_limited_v2(self):
        send = AsyncMock()
        await send_text(send, 'x' * 7001, ephemeral=True)
        self.assertEqual(send.await_count, 3)
        for call in send.call_args_list:
            self.assertTrue(call.kwargs['view'].has_components_v2())
            self.assertEqual(call.kwargs['allowed_mentions'].to_dict()['parse'], [])
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr == 'Embed' for n in ast.walk(source)))
        self.assertIn('intents.members = True', ast.unparse(source))
