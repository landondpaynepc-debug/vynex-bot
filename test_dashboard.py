import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord
from dashboard import (DashboardManager, DashboardView, RulesPager, ABOUT,
                       DASHBOARD_CHANNEL_ID, MENU_ID)
from rules import rules_parts
from tickets import OPEN_ID, TICKET_COLOR


async def stream(values):
    for value in values:
        yield value


def interaction(owner=42, guild=10):
    return NS(user=NS(id=owner), guild_id=guild,
              response=NS(send_message=AsyncMock(), edit_message=AsyncMock()))


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_menu_has_exact_three_choices(self):
        manager = DashboardManager(NS(), 10, NS())
        view = DashboardView(manager)
        self.assertTrue(view.is_persistent())
        root = view.to_components()[0]
        self.assertEqual(root['type'], 17)
        self.assertEqual(root['accent_color'], TICKET_COLOR)
        select = root['components'][-1]['components'][0]
        self.assertEqual(select['custom_id'], MENU_ID)
        self.assertEqual([option['label'] for option in select['options']],
                         ['About Vynex Tweaks', 'Rules', 'Assistance'])

    async def test_each_option_sends_private_panel_and_assistance_opens_ticket_menu(self):
        tickets = NS(open_ticket=AsyncMock())
        manager = DashboardManager(NS(), 10, tickets)
        for value in ('about', 'rules', 'assistance'):
            request = interaction()
            await manager.choose(request, value)
            sent = request.response.send_message.call_args.kwargs
            self.assertTrue(sent['ephemeral'])
            self.assertEqual(sent['allowed_mentions'].to_dict()['parse'], [])
            root = sent['view'].to_components()[0]
            self.assertEqual(root['accent_color'], TICKET_COLOR)
            if value == 'about':
                self.assertEqual(root['components'][0]['content'], ABOUT)
            elif value == 'rules':
                self.assertIsInstance(sent['view'], RulesPager)
            else:
                select = sent['view'].children[0].children[-1].children[0]
                self.assertEqual(select.custom_id, OPEN_ID)
                select._values = ['support']
                await select.callback(request)
                tickets.open_ticket.assert_awaited_once_with(request, 'support')

    async def test_rules_all_pages_fit_and_navigation_is_private(self):
        manager = DashboardManager(NS(), 10, NS())
        for index, part in enumerate(rules_parts()):
            pager = RulesPager(manager, 42, index)
            children = pager.to_components()[0]['components']
            self.assertEqual(children[0]['content'], part)
            self.assertLessEqual(sum(len(c.get('content', '')) for c in children), 4000)
        pager = RulesPager(manager, 42)
        request = interaction()
        await pager.next(request)
        self.assertEqual(request.response.edit_message.call_args.kwargs['view'].page, 1)
        stranger = interaction(123)
        await pager.next(stranger)
        stranger.response.edit_message.assert_not_called()

    async def test_refresh_reuses_dashboard_and_registers_persistent_view(self):
        channel = MagicMock(spec=discord.TextChannel)
        channel.guild = NS(id=10)
        channel.send = AsyncMock()
        bot = NS(user=NS(id=99), get_channel=lambda ident: channel if ident == DASHBOARD_CHANNEL_ID else None,
                 add_view=MagicMock())
        manager = DashboardManager(bot, 10, NS())
        manager.register_view()
        bot.add_view.assert_called_once()
        view = DashboardView(manager)
        message = NS(author=NS(id=99), edit=AsyncMock(), components=[NS(to_dict=lambda: view.to_components()[0])])
        channel.history = lambda **kw: stream([message])
        await manager.ensure_dashboard()
        await manager.ensure_dashboard()
        self.assertEqual(message.edit.await_count, 2)
        channel.send.assert_not_called()
