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
from music import MusicManager, MusicError, MusicPanel, PrimedAudio, source_query


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
    manager.prepare = AsyncMock(return_value=('local-audio.mp3', NS(cleanup=MagicMock())))
    request = NS(guild=guild, guild_id=10, user=NS(id=42, voice=NS(channel=channel)), channel=NS(send=AsyncMock()))
    return NS(manager=manager, request=request, guild=guild, voice=voice, channel=channel)


class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def test_spotify_request_searches_soundcloud_and_labels_source(self):
        f = fixture()
        url = 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
        with patch('music.spotify_title', new=AsyncMock(return_value='Song Artist')), patch('music.extract',
                return_value=dict(title='Matched', url='https://audio.example/a')) as extract:
            track = await f.manager.resolve(url)
        extract.assert_called_once_with('scsearch5:Song Artist')
        self.assertEqual(track['spotify'], url)

    async def test_cancelled_loading_cleans_late_temporary_file(self):
        f = fixture()
        resource = NS(cleanup=MagicMock())
        ready = asyncio.Event()
        async def delayed(*args):
            await ready.wait()
            return 'local.mp3', resource
        with patch('music.asyncio.to_thread', new=delayed):
            task = asyncio.create_task(MusicManager.prepare(f.manager, {}))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            ready.set()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        resource.cleanup.assert_called_once()

    async def test_soundcloud_lookup_and_preview_rejection(self):
        from music import extract
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = dict(entries=[])
            with self.assertRaisesRegex(MusicError, 'no matching results'):
                extract('scsearch1:unknown')
            factory.return_value.__enter__.return_value.extract_info.return_value = dict(url='https://audio.example/a', is_preview=True)
            with self.assertRaisesRegex(MusicError, 'subscription'):
                extract('https://soundcloud.com/artist/song')

    async def test_search_skips_unavailable_and_preview_results(self):
        from music import extract
        with patch('yt_dlp.YoutubeDL') as factory:
            factory.return_value.__enter__.return_value.extract_info.return_value = dict(entries=[
                None, dict(url='https://audio.example/preview', is_preview=True),
                dict(url='https://audio.example/private', availability='needs_auth'),
                dict(title='Public track', url='https://audio.example/full', duration=180)])
            self.assertEqual(extract('scsearch5:song')['title'], 'Public track')

    async def test_rate_limited_ack_does_not_raise_or_repeat_requests(self):
        f = fixture()
        request = NS(response=NS(send_message=AsyncMock(side_effect=discord.HTTPException(
            NS(status=429, reason='Too Many Requests', headers={'Retry-After':'120'}), 'Rate limited'))))
        self.assertFalse(await f.manager.acknowledge(request, 'Music'))
        self.assertFalse(await f.manager.acknowledge(request, 'Music'))
        request.response.send_message.assert_awaited_once()
        result = await f.manager.control(f.request, 'leave')
        self.assertIn('Left voice', result)
        f.voice.disconnect.assert_awaited_once()
    async def test_controls_do_not_wait_for_loading_lock(self):
        f = fixture()
        f.voice.is_playing.return_value = True
        await f.manager.lock.acquire()
        try:
            result = await asyncio.wait_for(f.manager.control(f.request, 'pause'), timeout=0.2)
            self.assertIn('paused', result)
            await asyncio.wait_for(f.manager.control(f.request, 'stop'), timeout=0.2)
            f.voice.stop.assert_called_once()
        finally:
            f.manager.lock.release()
            await f.manager.close()

    async def test_empty_audio_is_rejected_before_playback(self):
        f = fixture()
        f.manager.resolve = AsyncMock(return_value=dict(title='Blocked', url='https://audio.example/stream',
            webpage='https://youtube.com/watch?v=test', spotify=None))
        with patch('discord.FFmpegOpusAudio') as source:
            source.return_value.read.return_value = b''
            with self.assertRaisesRegex(MusicError, 'returned no sound'):
                await f.manager.play(f.request, 'Song')
            f.voice.play.assert_not_called()
            source.return_value.cleanup.assert_called_once()
            self.assertEqual(source.call_args.args[0], 'local-audio.mp3')
            f.manager.prepare.return_value[1].cleanup.assert_called_once()
        await f.manager.close()

    async def test_vc_chat_panel_has_all_buttons_and_is_reused(self):
        f = fixture()
        f.manager.text_channel = f.channel
        message = NS(channel=f.channel, edit=AsyncMock())
        f.channel.send = AsyncMock(return_value=message)
        await f.manager.publish_controls('Now playing')
        await f.manager.publish_controls('Paused')
        f.channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        panel = MusicPanel(f.manager)
        self.assertTrue(panel.is_persistent())
        container = panel.to_components()[0]
        self.assertEqual([button['label'] for row in container['components'] if row['type']==1
                          for button in row['components']], ['Pause', 'Resume', 'Skip', 'Queue', 'Stop', 'Leave'])

    async def test_verified_first_packet_is_preserved(self):
        original = NS(read=MagicMock(return_value=b'next'), cleanup=MagicMock())
        source = PrimedAudio(original, b'first')
        self.assertTrue(source.is_opus())
        self.assertEqual(source.read(), b'first')
        self.assertEqual(source.read(), b'next')
        source.cleanup()
        original.cleanup.assert_called_once()
    async def test_play_replaces_thinking_and_reports_timeout(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'play')
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        from ui_messages import text_view
        scope = dict(discord=discord, asyncio=asyncio, app_commands=app_commands,
            bot=NS(tree=tree, music=NS(play=AsyncMock(side_effect=asyncio.TimeoutError),
                acknowledge=AsyncMock(return_value=True))),
            server_only=check, text_view=text_view, MusicError=MusicError, logging=MagicMock())
        exec(compile(ast.Module(body=[command], type_ignores=[]), 'music-timeout-test', 'exec'), scope)
        request = NS(id=123, response=NS(send_message=AsyncMock()), edit_original_response=AsyncMock())
        await tree.get_command('play').callback(request, 'test song')
        self.assertEqual(request.edit_original_response.await_count, 1)
        first_text = scope['bot'].music.acknowledge.call_args.args[1]
        last = request.edit_original_response.call_args
        self.assertIn('Searching', first_text)
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
        self.assertEqual(source_query('https://soundcloud.com/artist/song')[0], 'soundcloud')
        for invalid in ('https://youtube.com/watch?v=test', 'http://soundcloud.com/artist/song', 'https://localhost/song',
                        'https://open.spotify.com/playlist/123', 'https://youtube.com:bad/watch'):
            with self.assertRaises(MusicError): source_query(invalid)

    async def test_join_uses_callers_channel_and_self_deafens(self):
        f = fixture()
        f.guild.voice_client = None
        await f.manager.connect(f.request)
        self.assertTrue(f.channel.connect.call_args.kwargs['self_deaf'])
        f.guild.voice_client = f.voice
        await f.manager.connect(f.request)
        f.guild.change_voice_state.assert_awaited_once_with(channel=f.channel, self_deaf=True, self_mute=False)

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

    async def test_song_search_uses_soundcloud_only(self):
        f = fixture()
        with patch('music.extract', return_value=dict(title='Song', url='https://audio.example/stream', webpage='https://soundcloud.com/artist/song')) as extract:
            await f.manager.resolve('Song Artist')
            extract.assert_called_once_with('scsearch5:Song Artist')
            await f.manager.resolve('https://soundcloud.com/artist/song')
            self.assertEqual(extract.call_args.args[0], 'https://soundcloud.com/artist/song')

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
        for name in ('play', 'joinvc', 'leave'):
            command = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            exec(compile(ast.Module(body=[command], type_ignores=[]), 'music-command-test', 'exec'), scope)
        self.assertIsNone(tree.get_command('music'))
        request = NS()
        scope['music_control_response'] = AsyncMock()
        await tree.get_command('joinvc').callback(request)
        scope['music_control_response'].assert_awaited_with(request, 'join')
        await tree.get_command('leave').callback(request)
        scope['music_control_response'].assert_awaited_with(request, 'leave')
        await client.close()
