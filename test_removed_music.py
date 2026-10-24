import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import discord
from ui_messages import text_view

class RemovedMusicTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_and_runtime_removed(self):
        source = Path(__file__).with_name('bot.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {n.name for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
        self.assertFalse(names & {'play', 'spotify', 'joinvc', 'leave', 'music_control_response'})
        for name in ('review', 'giveaway', 'generate', 'dashboard', 'rules'):
            self.assertIn(name, names)
        self.assertNotIn('from music import', source)
        self.assertNotIn('from spotify_client import', source)

    async def test_only_bot_owned_music_panels_are_retired(self):
        tree = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Bot')
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'retire_music_panels')
        scope = dict(GUILD_ID=10, discord=discord, text_view=text_view)
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'cleanup-test', 'exec'), scope)
        def message(author, custom_id):
            return NS(author=NS(id=author), components=[NS(to_dict=lambda:dict(type=17, components=[dict(custom_id=custom_id)]))], edit=AsyncMock())
        old = message(99, 'vynex:music:pause:v1')
        unrelated = message(99, 'vynex:giveaway:enter:v1')
        other = message(42, 'vynex:music:pause:v1')
        async def history(**kw):
            for item in (old, unrelated, other): yield item
        bot = NS(user=NS(id=99), get_guild=lambda ident:NS(voice_channels=[NS(id=20, history=history)]))
        await scope['retire_music_panels'](bot)
        old.edit.assert_awaited_once()
        unrelated.edit.assert_not_awaited()
        other.edit.assert_not_awaited()
