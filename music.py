"""Self-deafened SoundCloud voice playback."""
import asyncio
from collections import deque
from contextlib import suppress
import logging
import re
import tempfile
from pathlib import Path
import time
from urllib.parse import urlsplit

import aiohttp
import discord

from ui_messages import send_text, text_view, TICKET_COLOR


class MusicError(RuntimeError):
    pass


def attachment_track(attachment):
    if Path(attachment.filename).suffix.lower() != '.mp3':
        raise MusicError('Upload an MP3 file using the file option.')
    if not 0 < attachment.size <= 50 * 1024 * 1024:
        raise MusicError('The MP3 must be between 1 byte and 50 MB.')
    url = urlsplit(attachment.url)
    if url.scheme != 'https' or url.hostname not in ('cdn.discordapp.com', 'media.discordapp.net') or not url.path.startswith('/attachments/'):
        raise MusicError('Use a file uploaded directly through Discord.')
    return dict(title=attachment.filename, attachment=attachment, url=attachment.url,
                webpage='', duration=None, spotify=None)


async def download_attachment(attachment):
    attachment_track(attachment)
    resource = tempfile.TemporaryDirectory(prefix='vynex-upload-')
    target = Path(resource.name) / 'audio.mp3'
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(attachment.url, allow_redirects=False) as response:
                if response.status != 200:
                    raise MusicError('Discord could not load this upload. Attach the MP3 again.')
                size = 0
                with target.open('wb') as output:
                    async for chunk in response.content.iter_chunked(256 * 1024):
                        size += len(chunk)
                        if size > 50 * 1024 * 1024:
                            raise MusicError('The MP3 exceeds the 50 MB limit.')
                        output.write(chunk)
        if size == 0 or size != attachment.size:
            raise MusicError('The MP3 upload was incomplete. Attach it again.')
        return str(target), resource
    except BaseException:
        resource.cleanup()
        raise


class PrimedAudio(discord.AudioSource):
    """Keep the verified first Opus packet for the voice player's first read."""
    def __init__(self, source, first_packet, resource=None):
        self.source, self.first_packet = source, first_packet
        self.resource = resource

    def read(self):
        if self.first_packet is not None:
            packet, self.first_packet = self.first_packet, None
            return packet
        return self.source.read()

    def is_opus(self):
        return True

    def cleanup(self):
        try:
            self.source.cleanup()
        finally:
            if self.resource:
                self.resource.cleanup()


class MusicButton(discord.ui.Button):
    def __init__(self, manager, label, action):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f'vynex:music:{action}:v1')
        self.manager, self.action = manager, action

    async def callback(self, interaction):
        acknowledged = await self.manager.acknowledge(interaction, 'Applying music control…')
        succeeded = False
        try:
            result = await asyncio.wait_for(self.manager.control(interaction, self.action), timeout=20)
            succeeded = True
        except MusicError as error:
            result = str(error)
        except asyncio.TimeoutError:
            result = 'The voice action timed out. Try again or check the bot’s voice connection.'
        except Exception as error:
            logging.exception('Music control button failed.')
            result = f'Music control failed ({type(error).__name__}). Check the Render error.'
        if acknowledged:
            with suppress(discord.HTTPException):
                await interaction.edit_original_response(view=text_view(result), allowed_mentions=discord.AllowedMentions.none())
        if succeeded and self.manager.text_channel:
            with suppress(discord.HTTPException, asyncio.TimeoutError):
                title = self.manager.current['title'] if self.manager.current else 'Nothing'
                await asyncio.wait_for(self.manager.publish_controls(
                    f'## Music controls\n{result}\n\n**Current track:** {discord.utils.escape_markdown(title)}'), timeout=3)


class MusicPanel(discord.ui.LayoutView):
    def __init__(self, manager, text='## Music controls\nUse the buttons below while you are in this voice channel.'):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text), discord.ui.Separator(visible=False),
            discord.ui.ActionRow(*(MusicButton(manager, label, action) for label, action in
                [('Pause', 'pause'), ('Resume', 'resume'), ('Skip', 'skip'), ('Queue', 'queue')])),
            discord.ui.ActionRow(MusicButton(manager, 'Stop', 'stop'), MusicButton(manager, 'Leave', 'leave')),
            accent_colour=TICKET_COLOR))


def source_query(value):
    value = value.strip()
    if not value or len(value) > 300:
        raise MusicError('Enter a song name, SoundCloud track link or Spotify track link (up to 300 characters).')
    if '://' not in value:
        if value.startswith(('spotify:', '//')):
            raise MusicError('Use a song name or public SoundCloud track link.')
        return 'search', value
    url = urlsplit(value)
    try:
        port = url.port
    except ValueError as error:
        raise MusicError('That link contains an invalid port.') from error
    if url.scheme != 'https' or url.username or url.password or port not in (None, 443):
        raise MusicError('Use an HTTPS SoundCloud track link.')
    host = (url.hostname or '').lower()
    if host == 'open.spotify.com':
        match = re.fullmatch(r'/(?:intl-[a-z]{2}/)?track/([A-Za-z0-9]{22})/?', url.path)
        if not match:
            raise MusicError('Use an individual Spotify track link, not an album or playlist.')
        return 'spotify', f'https://open.spotify.com/track/{match[1]}'
    if host in ('soundcloud.com', 'www.soundcloud.com'):
        if not re.fullmatch(r'/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/?', url.path) or url.path.startswith('/discover/'):
            raise MusicError('Paste an individual SoundCloud track link, or enter the song and artist.')
        return 'soundcloud', 'https://soundcloud.com' + url.path
    raise MusicError('Use a song name or a SoundCloud track link. YouTube playback has been removed. Use /spotify for your personal Spotify device.')



async def spotify_title(url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async with session.get('https://open.spotify.com/oembed', params={'url': url}) as response:
            if response.status != 200:
                raise MusicError('Spotify could not read this track. Enter its song title and artist instead.')
            title = (await response.json()).get('title')
    if not isinstance(title, str) or not title.strip():
        raise MusicError('Spotify returned no song title. Enter the song and artist instead.')
    return title[:300]


def download_audio(track):
    """Download with native HTTP/HLS; FFmpeg only opens a local file."""
    import yt_dlp
    resource = tempfile.TemporaryDirectory(prefix='vynex-audio-')
    deadline = time.monotonic() + 25
    limit = 50 * 1024 * 1024
    def check(status):
        if time.monotonic() > deadline or status.get('downloaded_bytes', 0) > limit:
            raise MusicError('Audio loading exceeded the 25-second or 50 MB limit. Choose a shorter recording.')
    try:
        info = dict(track['download_info'])
        if (info.get('filesize') or 0) > limit:
            raise MusicError('This recording is too large to load. Choose a shorter recording.')
        with yt_dlp.YoutubeDL(dict(quiet=True, noprogress=True, no_warnings=True, noplaylist=True,
                outtmpl=str(Path(resource.name) / 'audio.%(ext)s'), socket_timeout=8,
                retries=0, fragment_retries=0, hls_prefer_native=True,
                concurrent_fragment_downloads=2, max_filesize=limit,
                progress_hooks=[check])) as downloader:
            downloader.process_info(info)
        files = [p for p in Path(resource.name).glob('audio.*')
                 if p.suffix not in ('.part', '.ytdl', '.temp') and p.is_file()]
        if len(files) != 1 or not 0 < files[0].stat().st_size <= limit:
            raise MusicError('The recording could not be loaded completely. Try another public track.')
        return str(files[0]), resource
    except BaseException:
        resource.cleanup()
        raise


def extract(query):
    import yt_dlp
    options = dict(format='bestaudio/best', quiet=True, no_warnings=True, noplaylist=True,
                   socket_timeout=15, retries=1, extractor_retries=1, cachedir=False,
                   skip_download=True, lazy_playlist=True, ignoreerrors=query.startswith('scsearch'))
    with yt_dlp.YoutubeDL(options) as extractor:
        info = extractor.extract_info(query, download=False)
        if info and 'entries' in info:
            info = next((entry for entry in info['entries'] if entry and entry.get('url') and not entry.get('is_preview') and entry.get('availability') not in ('premium_only', 'subscriber_only', 'needs_auth')), None)
    if not info:
        raise MusicError('SoundCloud returned no matching results that can play. Results may be protected, private or subscription-only. Add the artist name or paste a public playable SoundCloud track link.')
    if info.get('is_live'):
        raise MusicError('That result is a live stream. Choose a recorded track or paste its public SoundCloud track link.')
    if not info.get('url'):
        raise MusicError('This track has no accessible audio stream. It may be restricted or unavailable; try a different recording.')
    if info.get('is_preview') or info.get('availability') in ('premium_only', 'subscriber_only', 'needs_auth'):
        raise MusicError('This SoundCloud track requires a subscription or sign-in. Choose a public playable track.')
    duration = info.get('duration')
    if duration and duration > 7200:
        raise MusicError('Choose a track shorter than two hours.')
    return dict(title=info.get('title', 'Unknown track'), url=info['url'],
                webpage=info.get('webpage_url', ''), duration=duration, download_info=info)


class MusicManager:
    def __init__(self, bot, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.pending = deque()
        self.current = None
        self.lock = asyncio.Lock()
        self.idle = None
        self.text_channel = None
        self.generation = 0
        self.last_playback_error = ''
        self.control_message = None
        self.reply_blocked_until = 0

    async def acknowledge(self, interaction, text):
        if time.monotonic() < self.reply_blocked_until:
            return False
        try:
            await interaction.response.send_message(view=text_view(text), ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException as error:
            if error.status != 429:
                raise
            try:
                retry = max(60, float(error.response.headers.get('Retry-After', 60)))
            except (AttributeError, ValueError, TypeError):
                retry = 60
            self.reply_blocked_until = time.monotonic() + retry
            logging.warning('Discord rejected music acknowledgement with HTTP 429. Pausing music response requests for %s seconds; voice actions can still run.', retry)
            return False

    def register_view(self):
        self.bot.add_view(MusicPanel(self))

    async def publish_controls(self, text):
        if time.monotonic() < self.reply_blocked_until:
            return
        view = MusicPanel(self, text)
        if self.control_message and self.control_message.channel.id == self.text_channel.id:
            try:
                await self.control_message.edit(view=view, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.NotFound:
                self.control_message = None
        self.control_message = await self.text_channel.send(view=view, allowed_mentions=discord.AllowedMentions.none())

    def guild(self):
        return self.bot.get_guild(self.guild_id)

    def require_channel(self, interaction):
        if interaction.guild_id != self.guild_id:
            raise MusicError('Use music commands in the Vynex server.')
        channel = getattr(getattr(interaction.user, 'voice', None), 'channel', None)
        if not isinstance(channel, discord.VoiceChannel):
            raise MusicError('Join a normal voice channel first, then use the music command.')
        voice = interaction.guild.voice_client
        if voice and voice.is_connected() and voice.channel.id != channel.id:
            raise MusicError('Join the bot’s current voice channel to control music.')
        return channel

    async def connect(self, interaction):
        channel = self.require_channel(interaction)
        permissions = channel.permissions_for(interaction.guild.me)
        if not permissions.connect or not permissions.speak:
            raise MusicError('The bot needs Connect and Speak permissions in your voice channel.')
        voice = interaction.guild.voice_client
        try:
            if voice and voice.is_connected():
                await asyncio.wait_for(interaction.guild.change_voice_state(channel=channel, self_deaf=True, self_mute=False), timeout=8)
                return voice
            if voice:
                await voice.disconnect(force=True)
            return await asyncio.wait_for(channel.connect(self_deaf=True, self_mute=False, timeout=12, reconnect=False), timeout=15)
        except asyncio.CancelledError:
            partial = interaction.guild.voice_client
            if partial and not partial.is_connected():
                with suppress(Exception):
                    await asyncio.wait_for(partial.disconnect(force=True), timeout=3)
            raise
        except (discord.DiscordException, RuntimeError, asyncio.TimeoutError) as error:
            partial = interaction.guild.voice_client
            if partial and not partial.is_connected():
                with suppress(Exception):
                    await asyncio.wait_for(partial.disconnect(force=True), timeout=3)
            logging.error('Voice connection failed (%s).', type(error).__name__)
            raise MusicError('Voice connection failed. Check Connect/Speak permissions, voice dependencies, and host UDP access.') from error

    def cancel_idle(self):
        if self.idle:
            self.idle.cancel()
            self.idle = None

    async def idle_disconnect(self):
        await asyncio.sleep(180)
        async with self.lock:
            voice = self.guild().voice_client if self.guild() else None
            if voice and not self.current and not self.pending:
                await voice.disconnect(force=True)

    async def resolve(self, value):
        kind, query = source_query(value)
        spotify = query if kind == 'spotify' else None
        if spotify:
            query = await spotify_title(spotify)
        try:
            track = await asyncio.wait_for(asyncio.to_thread(extract,
                query if kind == 'soundcloud' else f'scsearch5:{query}'), timeout=25)
        except MusicError:
            raise
        except Exception as error:
            logging.error('SoundCloud lookup failed (%s).', type(error).__name__)
            raise MusicError('SoundCloud could not load that track. Try a public SoundCloud track link or add the artist name. Private, removed and subscription-only tracks cannot play.') from error
        track['spotify'] = spotify
        return track

    async def prepare(self, track):
        if track.get('attachment') is not None:
            return await download_attachment(track['attachment'])
        task = asyncio.create_task(asyncio.to_thread(download_audio, track))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            def discard(done):
                if not done.cancelled() and done.exception() is None:
                    done.result()[1].cleanup()
            task.add_done_callback(discard)
            raise

    async def play(self, interaction, value=None, progress=None, attachment=None):
        self.require_channel(interaction)
        if bool(value and value.strip()) == (attachment is not None):
            raise MusicError('Choose either a song query or an MP3 file, one per request.')
        generation = self.generation
        logging.info('Music stage: looking up track for guild %s.', self.guild_id)
        track = attachment_track(attachment) if attachment is not None else await self.resolve(value)
        async with self.lock:
            if generation != self.generation:
                raise MusicError('This play request was cancelled by Stop or Leave.')
            if len(self.pending) >= 50:
                raise MusicError('The queue is full (50 tracks). Wait or skip a track.')
            if progress:
                await progress('## Music\nTrack found. Connecting to your voice channel…')
            logging.info('Music stage: connecting to voice for guild %s.', self.guild_id)
            voice = await self.connect(interaction)
            if generation != self.generation:
                raise MusicError('This play request was cancelled by Stop or Leave.')
            if getattr(getattr(interaction.guild.me, 'voice', None), 'mute', False):
                raise MusicError('The bot is server-muted. Unmute it in Discord before playing music.')
            self.cancel_idle()
            self.text_channel = self.require_channel(interaction)
            track['requester'] = interaction.user.id
            track['queued'] = self.current is not None
            # Store the source page and resolve its temporary audio URL again when it reaches the front.
            self.pending.append(track)
            if not voice.is_playing() and not voice.is_paused() and self.current is None:
                if progress:
                    await progress('## Music\nConnected. Loading audio for playback…')
                await self.next_locked()
            if self.current is None and not self.pending:
                raise MusicError(self.last_playback_error or 'Playback could not start. Check the playback error shown in this channel.')
            return track

    async def next_locked(self):
        generation = self.generation
        voice = self.guild().voice_client if self.guild() else None
        if not voice or not voice.is_connected():
            self.pending.clear()
            self.current = None
            return
        self.current = None
        while self.pending:
            track = self.pending.popleft()
            try:
                import imageio_ffmpeg
                if not track.get('attachment') and (track.get('played_before') or track.get('queued')):
                    fresh = await self.resolve(track['webpage'])
                    track.update(url=fresh['url'], download_info=fresh['download_info'])
                if generation != self.generation:
                    return
                logging.info('Music stage: loading local audio for guild %s.', self.guild_id)
                local_path, resource = await self.prepare(track)
                if generation != self.generation:
                    resource.cleanup()
                    return
                try:
                    source = discord.FFmpegOpusAudio(local_path, executable=imageio_ffmpeg.get_ffmpeg_exe(), options='-vn')
                except BaseException:
                    resource.cleanup()
                    raise
                try:
                    first_packet = await asyncio.wait_for(asyncio.to_thread(source.read), timeout=10)
                    if not first_packet:
                        raise MusicError('The audio source returned no sound. Choose another public SoundCloud recording.')
                    if generation != self.generation:
                        source.cleanup()
                        resource.cleanup()
                        return
                except BaseException:
                    source.cleanup()
                    resource.cleanup()
                    raise
                source = PrimedAudio(source, first_packet, resource)
                self.current = track
                token = self.generation
                loop = asyncio.get_running_loop()
                def after(error, token=token):
                    if error:
                        logging.error('Voice playback ended with %s.', type(error).__name__)
                    asyncio.run_coroutine_threadsafe(self.finished(token), loop)
                try:
                    voice.play(source, after=after)
                except Exception:
                    source.cleanup()
                    raise
                for queued in self.pending:
                    queued['queued'] = True
                if self.text_channel:
                    with suppress(discord.HTTPException, asyncio.TimeoutError):
                        await asyncio.wait_for(self.publish_controls(
                            f'## Now playing\n**{discord.utils.escape_markdown(track["title"])}**\n'
                            f'Requested by <@{track["requester"]}>\n'
                            f'{"Uploaded MP3." if track.get("attachment") else "Spotify request matched to SoundCloud audio." if track.get("spotify") else "SoundCloud audio."}\n'
                            f'{track["webpage"]}'), timeout=4)
                return
            except Exception as error:
                logging.error('Track playback failed (%s).', type(error).__name__)
                self.current = None
                self.last_playback_error = (str(error) if isinstance(error, MusicError) else
                    'Audio could not start. The source timed out or refused playback. Try another public SoundCloud track.')
                if self.text_channel:
                    with suppress(discord.HTTPException, asyncio.TimeoutError):
                        await asyncio.wait_for(send_text(self.text_channel.send, self.last_playback_error), timeout=3)
        self.cancel_idle()
        self.idle = asyncio.create_task(self.idle_disconnect())

    async def finished(self, token):
        async with self.lock:
            if token == self.generation:
                await self.next_locked()

    async def control(self, interaction, action):
        self.require_channel(interaction)
        voice = interaction.guild.voice_client
        if action == 'join':
            async with self.lock:
                await self.connect(interaction)
            self.text_channel = self.require_channel(interaction)
            with suppress(discord.HTTPException, asyncio.TimeoutError):
                await asyncio.wait_for(self.publish_controls('## Music controls\nConnected and self-deafened. Use /play to add a track.'), timeout=3)
            self.cancel_idle()
            if not self.current:
                self.idle = asyncio.create_task(self.idle_disconnect())
            return 'Joined your voice channel, self-deafened.'
        if action not in ('stop', 'leave') and (not voice or not voice.is_connected()):
            raise MusicError('The bot is not connected. Use /play or /joinvc.')
        if action == 'queue':
            title = self.current['title'] if self.current else 'Nothing'
            return '**Now playing:** ' + discord.utils.escape_markdown(title) + '\n' + (
                '\n'.join(f'{index}. {discord.utils.escape_markdown(track["title"])}' for index, track in enumerate(list(self.pending)[:15], 1)) or 'The queue is empty.')
        if action == 'pause':
            if not voice.is_playing(): raise MusicError('Nothing is currently playing.')
            voice.pause()
            return 'Playback paused.'
        if action == 'resume':
            if not voice.is_paused(): raise MusicError('Playback is not paused.')
            voice.resume()
            return 'Playback resumed.'
        if action == 'skip':
            if not self.current: raise MusicError('Nothing is currently playing.')
            voice.stop()
            return 'Skipped the current track.'
        if action in ('stop', 'leave'):
            self.generation += 1
            self.pending.clear()
            self.current = None
            self.cancel_idle()
            if voice:
                voice.stop()
            if action == 'leave' and voice:
                await asyncio.wait_for(voice.disconnect(force=True), timeout=3)
            elif action == 'stop':
                self.idle = asyncio.create_task(self.idle_disconnect())
            return 'Stopped playback and cleared the queue.' if action == 'stop' else 'Left voice and cleared the queue.'
        raise MusicError('Choose a supported music control.')

    async def close(self):
        self.generation += 1
        self.cancel_idle()
        self.pending.clear()
        voice = self.guild().voice_client if self.guild() else None
        if voice:
            await voice.disconnect(force=True)
