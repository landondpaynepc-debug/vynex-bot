import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

import aiohttp
import discord
from discord import app_commands
from health_server import HealthServer, configured_port


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_liveness_readiness_and_cleanup(self):
        ready = False
        health = HealthServer(lambda: ready)
        port = await health.start(port=0)
        self.assertEqual(await health.start(), port)
        try:
            async with aiohttp.ClientSession() as session:
                for route in ('/', '/health'):
                    async with session.get(f'http://127.0.0.1:{port}{route}') as response:
                        self.assertEqual(response.status, 200)
                        self.assertFalse((await response.json())['discord_ready'])
                async with session.get(f'http://127.0.0.1:{port}/ready') as response:
                    self.assertEqual(response.status, 503)
                ready = True
                async with session.get(f'http://127.0.0.1:{port}/ready') as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue((await response.json())['discord_ready'])
        finally:
            await health.close()
            await health.close()
        self.assertIsNone(health.runner)
        replacement = HealthServer(lambda: True)
        await replacement.start(port=port)
        await replacement.close()

    async def test_render_port_configuration(self):
        with patch.dict(os.environ, {'PORT':'14321'}):
            self.assertEqual(configured_port(), 14321)
        for value in ('bad', '0', '-1', '65536'):
            with patch.dict(os.environ, {'PORT':value}):
                with self.assertRaises(ValueError): configured_port()

    async def test_bot_opens_port_before_command_sync_and_closes_it(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        bot_class = next(n for n in source.body if isinstance(n,ast.ClassDef) and n.name=='Bot')
        events = []
        class FakeHealth:
            def __init__(self, is_ready): pass
            async def start(self): events.append('http'); return 10000
            async def close(self): events.append('cleanup')
        class FakeTickets:
            def __init__(self, *args): pass
            def register_views(self): events.append('views')
        globals_ = {'discord':discord,'app_commands':app_commands,'HealthServer':FakeHealth,'TicketManager':FakeTickets,
                    'RulesManager':FakeTickets,
                    'EventLogs':FakeTickets,
                    'GUILD_ID':1,'KEY_ROLE_ID':0,'logging':SimpleNamespace(info=lambda *a:None)}
        exec(compile(ast.Module(body=[bot_class],type_ignores=[]),'bot-lifecycle-test','exec'),globals_)
        bot = globals_['Bot']()
        async def sync(**kw): events.append('sync'); return []
        bot.tree.sync = sync
        await bot.setup_hook()
        await bot.close()
        self.assertEqual(events,['http','views','sync','cleanup'])


if __name__ == '__main__': unittest.main(verbosity=2)
