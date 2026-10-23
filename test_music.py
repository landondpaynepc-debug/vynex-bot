import ast
import asyncio
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands
from music import MusicManager, MusicError, source_query


def fixture():
    channel = MagicMock(spec=discord.VoiceChannel)
    channel.id = 5
    channel.permissions_for.return_value = NS(connect=True, speak=True)
    voice = MagicMock()
    voice.channel = channel
    voice.is_connected.return_value = True
    voice.is_playing.return_value = False
    voice.is_paused.return_value = False
    voice.disconnect = AsyncMock()
    channel.connect = AsyncMock(return_value=voice)
    guild = NS(id=10, me=NS(), voice_client=voice, change_voice_state=AsyncMock())
    bot = NS(get_guild=lambda ident: guild)
    manager = MusicManager(bot, 10)
    request = NS(guild=guild, guild_id=10, user=NS(id=42, voice=NS(channel=channel)), channel=NS(send=AsyncMock()))
    return NS(manager=manager, request=request, guild=guild, voice=voice, channel=channel)


class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def test_play_replaces_thinking_and_reports_timeout(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'play')
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        from ui_messages import text_view
        scope = dict(discord=discord, asyncio=asyncio, app_commands=app_commands,
            bot=NS(tree=tree, music=NS(play=AsyncMock(side_effect=asyncio.TimeoutError))),
            server_only=check, text_view=text_view, MusicError=MusicError, logging=MagicMock())
        exec(compile(ast.Module(body=[command], type_ignores=[]), 'music-timeout-test', 'exec'), scope)
        request = NS(id=123, response=NS(defer=AsyncMock()), edit_original_response=AsyncMock())
        await tree.get_command('play').callback(request, 'test song')
        self.assertEqual(request.edit_original_response.await_count, 2)
        first, last = request.edit_original_response.call_args_list
        self.assertIn('Searching', first.kwargs['view'].to_components()[0]['components'][0]['content'])
        self.assertIn('timed out', last.kwargs['view'].to_components()[0]['components'][0]['content'])
        await client.close()

    async def test_voice_connection_timeout_is_actionable(self):
        f = fixture()
        f.guild.voice_client = None
        f.channel.connect.side_effect = asyncio.TimeoutError
        with self.assertRaisesRegex(MusicError, 'Voice connection failed'):
            await f.manager.connect(f.request)

    async def test_real_ffmpeg_encodes_non_opus_audio(self):
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'audio.wav')
            subprocess.run([executable, '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=0.1', '-y', path], check=True, capture_output=True)
            source = discord.FFmpegOpusAudio(path, executable=executable)
            try:
                packets = []
                while packet := source.read():
                    packets.append(packet)
                self.assertTrue(packets, 'Audio must be encoded to Opus rather than copied from a different codec.')
            finally:
                source.cleanup()
    async def test_sources_and_spotify_track_validation(self):
        self.assertEqual(source_query('song and artist'), ('search', 'song and artist'))
        self.assertEqual(source_query('https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=test')[0], 'spotify')
        for invalid in ('http://youtube.com/watch?v=test', 'https://localhost/song',
                        'https://open.spotify.com/playlist/123', 'https://youtube.com:bad/watch'):
            with self.assertRaises(MusicError): source_query(invalid)

    async def test_join_uses_callers_channel_and_self_deafens(self):
        f = fixture()
        f.guild.voice_client = None
        await f.manager.connect(f.request)
        self.assertTrue(f.channel.connect.call_args.kwargs['self_deaf'])
        f.guild.voice_client = f.voice
        await f.manager.connect(f.request)
        f.guild.change_voice_state.assert_awaited_once_with(channel=f.channel, self_deaf=True)

    async def test_no_voice_wrong_voice_and_missing_permissions(self):
        f = fixture()
        f.request.user.voice = None
        with self.assertRaises(MusicError): await f.manager.connect(f.request)
        f.request.user.voice = NS(channel=f.channel)
        f.voice.channel = NS(id=999)
        with self.assertRaises(MusicError): await f.manager.connect(f.request)
        f.voice.channel = f.channel
        f.channel.permissions_for.return_value.speak = False
        with self.assertRaises(MusicError): await f.manager.connect(f.request)

    async def test_spotify_uses_metadata_search_and_never_spotify_audio(self):
        f = fixture()
        with patch('music.spotify_title', new=AsyncMock(return_value='Song Artist')), patch('music.extract',
                return_value=dict(title='Matched song', url='https://audio.example/stream', webpage='https://youtube.com/watch?v=test')) as extract:
            track = await f.manager.resolve('https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT')
        extract.assert_called_once_with('ytsearch1:Song Artist')
        self.assertIn('spotify.com', track['spotify'])
        self.assertNotIn('spotify.com', track['url'])

    async def test_play_queue_stop_and_callback_do_not_restart_stopped_music(self):
        f = fixture()
        track = dict(title='Test song', url='https://audio.example/stream', webpage='https://youtube.com/watch?v=test', spotify=None)
        f.manager.resolve = AsyncMock(side_effect=lambda value: dict(track))
        with patch('discord.FFmpegOpusAudio'):
            await f.manager.play(f.request, 'Song')
            self.assertEqual(f.manager.current['title'], 'Test song')
            f.voice.is_playing.return_value = True
            await f.manager.play(f.request, 'Song 2')
            self.assertEqual(len(f.manager.pending), 1)
            self.assertTrue(f.manager.pending[0]['queued'])
            token = f.manager.generation
            await f.manager.control(f.request, 'stop')
            await f.manager.finished(token)
            self.assertFalse(f.manager.pending)
            self.assertIsNone(f.manager.current)
            self.assertEqual(f.voice.play.call_count, 1)
        await f.manager.close()

    async def test_music_commands_register(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        scope = dict(discord=discord, app_commands=app_commands, bot=NS(tree=tree), server_only=check)
        for name in ('play', 'music'):
            command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[command], type_ignores=[]), 'music-command-test', 'exec'), scope)
        self.assertEqual(len(tree.get_command('music').to_dict(tree)['options'][0]['choices']), 7)
        await client.close()
