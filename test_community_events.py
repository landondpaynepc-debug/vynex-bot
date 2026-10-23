import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

from community_events import (GiveawayManager, GiveawayView, STATE_FILE,
                              duration_seconds, review_view)
from ui_messages import TICKET_COLOR


async def stream(values):
    for value in values:
        yield value


def fixture():
    records = []
    public = MagicMock(spec=discord.TextChannel)
    public.guild = NS(id=10)
    message = NS(id=555, jump_url='https://discord.com/channels/10/20/555',
                 edit=AsyncMock(), delete=AsyncMock())
    public.send = AsyncMock(return_value=message)
    public.fetch_message = AsyncMock(return_value=message)
    registry = MagicMock(spec=discord.TextChannel)
    registry.guild = NS(id=10)
    registry.history = lambda **kw: stream(records)
    async def save(**kw):
        data = kw['file'].fp.read()
        attachment = NS(filename=STATE_FILE, read=AsyncMock(return_value=data))
        record = NS(id=888, author=NS(id=99), attachments=[attachment])
        async def edit(**payload):
            attachment.read.return_value = payload['attachments'][0].fp.read()
        record.edit = AsyncMock(side_effect=edit)
        records.append(record)
        return record
    registry.send = AsyncMock(side_effect=save)
    from event_logs import LOG_CHANNEL_ID
    bot = NS(user=NS(id=99), get_channel=lambda ident: registry if ident == LOG_CHANNEL_ID else public)
    manager = GiveawayManager(bot, 10)
    request = NS(channel=public, channel_id=20, user=NS(id=42), guild_id=10)
    def entry(user=42):
        return NS(guild_id=10, message=message, user=NS(id=user, bot=False),
            response=NS(defer=AsyncMock(), send_message=AsyncMock()), followup=NS(send=AsyncMock()))
    return NS(manager=manager, bot=bot, request=request, entry=entry,
              message=message, registry=registry, records=records)


class CommunityEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_state_reloads_durable_record_before_rejecting_entry(self):
        f = fixture()
        await f.manager.create(f.request, 'Prize', 'Text', 3600)
        f.manager.states.clear()
        await f.manager.enter(f.entry())
        self.assertIn('42', f.manager.states[555][0]['entries'])

    async def test_orphan_empty_panel_is_saved_and_accepts_entry(self):
        f = fixture()
        state = dict(ended=False, prize='One package', description='Good luck!', host=42,
                     entries={}, ends=9999999999)
        f.message.author = f.bot.user
        f.message.channel = f.request.channel
        f.message.channel.id = 20
        f.message.components = [discord.components._component_factory(root)
            for root in GiveawayView(f.manager, state).to_components()]
        f.manager.loaded = True
        await f.manager.enter(f.entry())
        self.assertEqual(f.manager.states[555][0]['ends'], 9999999999)
        self.assertIn('42', f.manager.states[555][0]['entries'])
        self.assertEqual(len(f.records), 1)

    async def test_unknown_panel_never_discards_existing_entries(self):
        f = fixture()
        state = dict(ended=False, prize='Prize', description='Text', host=42,
                     entries={'43': 'Member'}, ends=9999999999)
        f.message.author = f.bot.user
        f.message.components = [discord.components._component_factory(root)
            for root in GiveawayView(f.manager, state).to_components()]
        f.manager.loaded = True
        request = f.entry()
        await f.manager.enter(request)
        self.assertFalse(f.manager.states)
        reply = request.followup.send.call_args.kwargs['view'].to_components()[0]['components'][0]['content']
        self.assertIn('record is unavailable', reply)
        self.assertNotIn('has ended', reply)
        self.assertFalse(f.records)

    async def test_production_errors_identify_http_code_and_command(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        handler = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'error_handler')
        handler.decorator_list = []
        reply = AsyncMock()
        scope = dict(discord=discord, app_commands=app_commands, VynexError=type('VynexError', (Exception,), {}),
                     logging=NS(error=MagicMock()), reply=reply)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'error-handler-test', 'exec'), scope)
        request = NS(id=1234, command=NS(name='review'))
        error = discord.HTTPException(NS(status=400, reason='Bad Request'), {'code':50035, 'message':'Invalid form'})
        await scope['error_handler'](request, NS(original=error))
        message = reply.call_args.args[1]
        for expected in ('review', '400', '50035', '1234'):
            self.assertIn(expected, message)

    async def test_complete_review_and_giveaway_callbacks(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        f = fixture()
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        replies = AsyncMock()
        scope = dict(discord=discord, app_commands=app_commands,
            bot=NS(tree=tree, giveaways=f.manager), server_only=check,
            reply=replies, review_view=review_view, duration_seconds=duration_seconds)
        for name in ('review', 'giveaway'):
            command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[command], type_ignores=[]), 'full-command-test', 'exec'), scope)
        request = NS(user=NS(id=42), response=NS(send_message=AsyncMock(), defer=AsyncMock()),
                     followup=NS(send=AsyncMock()))
        for package in (None, app_commands.Choice(name='VYNEX Premium Package', value='VYNEX Premium Package')):
            await tree.get_command('review').callback(request, 5, 'Great tweaks!', package)
        self.assertEqual(request.response.defer.await_count, 2)
        self.assertEqual(request.followup.send.await_count, 2)
        f.request.response = NS(defer=AsyncMock())
        await tree.get_command('giveaway').callback(f.request, 'Premium key', '2h', 'Enter to win!')
        f.registry.send.assert_awaited_once()
        replies.assert_awaited_once()
        await client.close()

    async def test_duration_and_star_display(self):
        self.assertEqual(duration_seconds('2h'), 7200)
        for invalid in ('0m', '31d', '-1h', 'tomorrow', '1s'):
            with self.assertRaises(ValueError): duration_seconds(invalid)
        for stars in range(1, 6):
            root = review_view(NS(id=42), stars, 'Vynex Tweaks', 'Great tweaks').to_components()[0]
            self.assertEqual(root['type'], 17)
            self.assertEqual(root['accent_color'], TICKET_COLOR)
            text = root['components'][0]['content']
            self.assertIn('★' * stars + '☆' * (5-stars), text)
            self.assertIn(f'{stars}/5', text)
            self.assertIn('42', text)

    async def test_commands_register_rating_bounds_and_staff_only_giveaway(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        scope = dict(discord=discord, app_commands=app_commands, bot=NS(tree=tree), server_only=check)
        for name in ('review', 'giveaway'):
            command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[command], type_ignores=[]), 'command-test', 'exec'), scope)
        option = tree.get_command('review').to_dict(tree)['options'][0]
        self.assertEqual((option['min_value'], option['max_value']), (1, 5))
        self.assertTrue(tree.get_command('giveaway').default_permissions.manage_guild)
        await client.close()

    async def test_duplicate_entries_and_restart_recovery(self):
        f = fixture()
        with patch('community_events.time.time', return_value=10):
            await f.manager.create(f.request, 'Premium access', 'Custom giveaway text', 60)
            await asyncio.gather(f.manager.enter(f.entry()), f.manager.enter(f.entry()), f.manager.enter(f.entry(43)))
        self.assertEqual(len(f.manager.states[555][0]['entries']), 2)
        restored = GiveawayManager(f.bot, 10)
        await restored.load()
        self.assertEqual(set(restored.states[555][0]['entries']), {'42', '43'})
        self.assertTrue(GiveawayView(restored, restored.states[555][0]).is_persistent())
        with patch('community_events.time.time', return_value=100), patch('community_events.secrets.choice', return_value='43') as choose:
            await restored.tick()
            choose.assert_called_once()
        saved = json.loads(await f.records[0].attachments[0].read())
        self.assertEqual(saved['winner'], '43')
        self.assertTrue(saved['ended'])
        root = f.message.edit.call_args.kwargs['view'].to_components()[0]
        self.assertIn('<@43>', root['components'][0]['content'])
        self.assertTrue(root['components'][-1]['components'][0]['disabled'])
        self.assertFalse(restored.states)

    async def test_empty_giveaway_and_deadline_reject_entry(self):
        f = fixture()
        with patch('community_events.time.time', return_value=10):
            await f.manager.create(f.request, 'Prize', 'Text', 60)
        with patch('community_events.time.time', return_value=100), patch('community_events.secrets.choice') as choose:
            await f.manager.enter(f.entry())
            await f.manager.tick()
            choose.assert_not_called()
        root = f.message.edit.call_args.kwargs['view'].to_components()[0]
        self.assertIn('Nobody entered', root['components'][0]['content'])

    async def test_result_is_not_redrawn_after_announcement_failure(self):
        f = fixture()
        with patch('community_events.time.time', return_value=10):
            await f.manager.create(f.request, 'Prize', 'Text', 60)
            await f.manager.enter(f.entry())
        f.message.edit.side_effect = discord.HTTPException(NS(status=500, reason='Test'), 'simulated')
        with patch('community_events.time.time', return_value=100), patch('community_events.secrets.choice', return_value='42'):
            await f.manager.tick()
        restored = GiveawayManager(f.bot, 10)
        await restored.load()
        self.assertEqual(restored.states[555][0]['winner'], '42')
        f.message.edit.side_effect = None
        with patch('community_events.secrets.choice') as choose:
            await restored.tick()
            choose.assert_not_called()

    async def test_storage_failure_does_not_confirm_entry(self):
        f = fixture()
        with patch('community_events.time.time', return_value=10):
            await f.manager.create(f.request, 'Prize', 'Text', 60)
            f.records[0].edit.side_effect = RuntimeError('Storage unavailable')
            await f.manager.enter(f.entry())
        self.assertEqual(f.manager.states[555][0]['entries'], {})
