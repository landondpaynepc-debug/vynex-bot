import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord

from rules import RULES_CHANNEL_ID, RULES_TEXT, RulesManager, RulesView, rules_parts
from tickets import TICKET_COLOR


async def stream(values):
    for value in values:
        yield value


class RulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_rules_fit_dark_gray_v2_messages(self):
        parts = rules_parts()
        self.assertEqual('\n\n'.join(parts), RULES_TEXT)
        self.assertGreater(len(parts), 1)
        for index, text in enumerate(parts, 1):
            view = RulesView(text, index, len(parts))
            self.assertTrue(view.has_components_v2())
            root = view.to_components()[0]
            self.assertEqual(root['type'], 17)
            self.assertEqual(root['accent_color'], TICKET_COLOR)
            self.assertLessEqual(sum(len(c.get('content', '')) for c in root['components']), 4000)
        for number in range(1, 21):
            self.assertIn(f'*{number}. ', RULES_TEXT)
        self.assertIn('# Moderation & Punishments', RULES_TEXT)
        self.assertIn('# Final Notice', RULES_TEXT)

    async def test_reconnect_updates_without_duplicates_or_mentions(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = NS(id=10)
        messages = []
        channel.history = lambda **kw: stream(messages)
        async def send(**kw):
            self.assertEqual(kw['allowed_mentions'].to_dict()['parse'], [])
            message = NS(author=NS(id=99), edit=AsyncMock(),
                components=[NS(to_dict=lambda value=value: value) for value in kw['view'].to_components()])
            messages.append(message)
            return message
        channel.send = AsyncMock(side_effect=send)
        bot = NS(user=NS(id=99), get_channel=lambda ident: channel if ident == RULES_CHANNEL_ID else None)
        manager = RulesManager(bot, 10)
        await manager.ensure_rules()
        await manager.ensure_rules()
        self.assertEqual(channel.send.await_count, len(rules_parts()))
        for message in messages:
            message.edit.assert_awaited_once()
            self.assertEqual(message.edit.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])

    async def test_wrong_server_is_rejected(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = NS(id=20)
        manager = RulesManager(NS(get_channel=lambda ident: channel), 10)
        with self.assertRaises(RuntimeError):
            await manager.ensure_rules()
        channel.send.assert_not_called()
