"""Premium license issuing and Discord moderation. Python 3.10+."""
import logging
import asyncio
import os
from pathlib import Path
import sqlite3
from datetime import timedelta

import discord
from vynex_client import VynexClient, VynexError
from health_server import HealthServer
from tickets import TicketManager
from rules import RulesManager
from event_logs import EventLogs
from dashboard import DashboardManager
from welcome import WelcomeManager
from ui_messages import send_text, text_view
from community_events import GiveawayManager, review_view, duration_seconds
from music import MusicManager, MusicError
from spotify_client import SpotifyClient, SpotifyError, SpotifyPanel
from discord import app_commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
def setting_id(name, optional=False):
    value = os.getenv(name, '').strip()
    if optional and (not value or value == '0'):
        return 0
    if not value.isdecimal() or not 0 < int(value) < 2**64:
        raise SystemExit(
            f"Setup needed: {name} must be a numeric Discord ID.\n"
            f"Copy .env.example to .env in {ROOT}, then fill in your settings.\n"
            "For GUILD_ID: Discord Settings > Advanced > Developer Mode, "
            "then right-click your server and choose Copy Server ID."
        )
    return int(value)


GUILD_ID = setting_id('GUILD_ID')
KEY_ROLE_ID = setting_id('KEY_ROLE_ID', optional=True)
COMPANY = os.getenv('COMPANY_NAME', 'Vynex Tweaks')
vynex = VynexClient(os.getenv('VYNEX_API_URL', ''), os.getenv('VYNEX_ADMIN_PASSWORD', ''))
logging.basicConfig(level=logging.INFO)


def database():
    db = sqlite3.connect(ROOT / 'bot.sqlite3')
    db.row_factory = sqlite3.Row
    return db


with database() as db:
    db.executescript('''
    CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY, guild INTEGER NOT NULL, member INTEGER NOT NULL,
        moderator INTEGER NOT NULL, reason TEXT NOT NULL,
        created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ''')


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.moderation = True
        intents.members = True
        super().__init__(intents=intents,
                         allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.health_server = HealthServer(self.is_ready)
        self.tickets = TicketManager(self, GUILD_ID)
        self.rules = RulesManager(self, GUILD_ID)
        self.event_logs = EventLogs(self, GUILD_ID)
        self.dashboard = DashboardManager(self, GUILD_ID, self.tickets)
        self.welcome = WelcomeManager(self, GUILD_ID)
        self.giveaways = GiveawayManager(self, GUILD_ID)
        self.music = MusicManager(self, GUILD_ID)
        self.spotify = SpotifyClient(vynex.base_url, vynex.password)

    async def close(self):
        try:
            await self.giveaways.close()
            await self.music.close()
            await self.health_server.close()
        finally:
            await super().close()

    async def setup_hook(self):
        logging.info('Community commands diagnostic build 2; discord.py %s.', discord.__version__)
        port = await self.health_server.start()
        logging.info('Render health server listening on 0.0.0.0:%s', port)
        self.tickets.register_views()
        self.dashboard.register_view()
        self.giveaways.register_view()
        self.music.register_view()
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logging.info('Registered commands for this instance: %s', ', '.join(command.name for command in synced))
        logging.info('Package selector version 1: synced %s commands for server %s; /generate requires tweaks or premium.', len(synced), GUILD_ID)

    async def on_ready(self):
        self.giveaways.start()
        for name, refresh in (('shop panel', self.tickets.ensure_panel),
                              ('open ticket messages', self.tickets.refresh_open_tickets),
                              ('community rules', self.rules.ensure_rules),
                              ('event logs', self.event_logs.check),
                              ('community dashboard', self.dashboard.ensure_dashboard),
                              ('welcome channel', self.welcome.check),
                              ('automatic member role', self.welcome.check_auto_role)):
            try:
                await refresh()
                logging.info('Dark gray Components V2 %s refreshed.', name)
            except (discord.HTTPException, RuntimeError) as error:
                logging.error('%s refresh failed (%s). Check configured channels and bot permissions.', name, type(error).__name__)

    async def on_raw_message_delete(self, payload):
        await self.event_logs.deleted(payload)

    async def on_member_join(self, member):
        await self.welcome.assign_role(member)
        await self.welcome.joined(member)

    async def on_raw_bulk_message_delete(self, payload):
        await self.event_logs.deleted(payload)

    async def on_audit_log_entry_create(self, entry):
        await self.event_logs.audit_entry(entry)

    async def on_app_command_completion(self, interaction, command):
        await self.event_logs.command_completed(interaction, command)


bot = Bot()


async def server_only(i):
    if i.guild_id != GUILD_ID or not isinstance(i.user, discord.Member):
        raise app_commands.CheckFailure('Use this command in the configured server.')
    return True


async def key_staff(i):
    await server_only(i)
    if i.user.guild_permissions.administrator or any(r.id == KEY_ROLE_ID for r in i.user.roles):
        return True
    raise app_commands.CheckFailure('Only administrators or the configured key staff role can manage keys.')


async def reply(i, text=None, **kwargs):
    async def sender(**payload):
        send = i.followup.send if i.response.is_done() else i.response.send_message
        return await send(ephemeral=True, **payload)
    await send_text(sender, text, **kwargs)


def target_check(i, member):
    if member.id in (i.user.id, bot.user.id, i.guild.owner_id):
        raise app_commands.CheckFailure('You cannot moderate yourself, this bot, or the server owner.')
    if i.user.id != i.guild.owner_id and member.top_role >= i.user.top_role:
        raise app_commands.CheckFailure('That member has an equal or higher role than you.')
    if member.top_role >= i.guild.me.top_role:
        raise app_commands.CheckFailure('Move the bot role above that member’s highest role.')


def audit(i, reason):
    return f'{i.user} ({i.user.id}): {reason}'[:512]


@bot.tree.command(description='Post or refresh the Vynex Components V2 shop and support panel.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def shop(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    try:
        panel = await bot.tickets.ensure_panel()
        await bot.tickets.refresh_open_tickets()
        await reply(i, f'Ticket panel and open ticket messages refreshed: {panel.jump_url}')
    except (discord.HTTPException, RuntimeError):
        await reply(i, 'Unable to publish the panel. Check the configured channels and bot permissions.')


@bot.tree.command(description='Join your voice channel and play a song name, YouTube link or Spotify track link.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.checks.cooldown(1, 5)
async def play(i: discord.Interaction, query: app_commands.Range[str, 1, 300]):
    acknowledged = await bot.music.acknowledge(i, '## Music\nSearching for your track…')
    async def progress(message):
        if acknowledged:
            try:
                await i.edit_original_response(view=text_view(message), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as error:
                logging.warning('Music progress response rejected: HTTP %s, code %s.', error.status, error.code)
    try:
        track = await asyncio.wait_for(bot.music.play(i, query, progress=progress), timeout=45)
        await progress(f'Added **{discord.utils.escape_markdown(track["title"])}** to playback. The bot is self-deafened.')
    except asyncio.TimeoutError:
        logging.error('Music request %s timed out after 45 seconds.', i.id)
        await progress('## Music request timed out\nThe audio source or voice connection did not respond within 45 seconds. Try a direct YouTube link. If the bot cannot join voice, check Connect/Speak permissions and Render voice connectivity.')
    except MusicError as error:
        await progress(str(error))
    except Exception as error:
        logging.exception('Music request %s failed.', i.id)
        await progress(f'Music could not start ({type(error).__name__}). Reference: {i.id}. Check the matching Render error.')


async def music_control_response(i, action):
    acknowledged = await bot.music.acknowledge(i, '## Music controls\nApplying your music control…')
    async def status(message):
        if acknowledged:
            try:
                await i.edit_original_response(view=text_view(message), allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as error:
                logging.warning('Music control response rejected: HTTP %s, code %s.', error.status, error.code)
    try:
        await status(await asyncio.wait_for(bot.music.control(i, action), timeout=20))
    except asyncio.TimeoutError:
        await status('The voice action timed out. Check voice permissions and host connectivity, then try again.')
    except MusicError as error:
        await status(str(error))


@bot.tree.command(description='Link your Spotify account and control playback on your own Spotify devices.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.checks.cooldown(1, 3)
@app_commands.choices(action=[app_commands.Choice(name=name, value=value) for name, value in [
    ('Link account', 'link'), ('Now playing', 'status'), ('Devices', 'devices'), ('Resume', 'play'),
    ('Pause', 'pause'), ('Next', 'next'), ('Previous', 'previous'), ('Select device', 'device'), ('Unlink account', 'unlink')]])
async def spotify(i: discord.Interaction, action: app_commands.Choice[str], device: app_commands.Range[str, 1, 128] = None):
    await i.response.send_message(view=text_view('Contacting Spotify…'), ephemeral=True,
                                  allowed_mentions=discord.AllowedMentions.none())
    try:
        data = await bot.spotify.request(i.user.id, action.value, device)
        view = SpotifyPanel(bot.spotify, i.user.id, action.value, data)
    except SpotifyError as error:
        view = text_view(str(error))
    await i.edit_original_response(view=view, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(description='Join your current voice channel, self-deafened, without starting music.')
@app_commands.guild_only()
@app_commands.check(server_only)
async def joinvc(i: discord.Interaction):
    await music_control_response(i, 'join')


@bot.tree.command(description='Leave voice and stop any music or pending playback.')
@app_commands.guild_only()
@app_commands.check(server_only)
async def leave(i: discord.Interaction):
    await music_control_response(i, 'leave')


@bot.tree.command(description='Review Vynex Tweaks or Premium with a rating out of five stars.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.checks.cooldown(1, 300)
@app_commands.choices(package=[app_commands.Choice(name='Vynex Tweaks', value='Vynex Tweaks'),
                              app_commands.Choice(name='VYNEX Premium Package', value='VYNEX Premium Package')])
async def review(i: discord.Interaction, stars: app_commands.Range[int, 1, 5],
                 text: app_commands.Range[str, 1, 1500], package: app_commands.Choice[str] = None):
    await i.response.defer()
    application = package.value if package else 'Vynex Tweaks'
    await i.followup.send(view=review_view(i.user, stars, application, text),
                                  allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(description='Start a giveaway with a prize, custom text and duration (10m, 2h, 7d).')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(i: discord.Interaction, prize: app_commands.Range[str, 1, 200],
                   duration: str, text: app_commands.Range[str, 1, 1600]):
    try:
        seconds = duration_seconds(duration)
    except ValueError as error:
        return await reply(i, str(error))
    await i.response.defer(ephemeral=True)
    message = await bot.giveaways.create(i, prize, text, seconds)
    await reply(i, f'Giveaway started: {message.jump_url}')


@bot.tree.command(description='Send a welcome preview to the configured welcome channel.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def welcometest(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    ok = await bot.welcome.joined(i.user)
    await reply(i, 'Welcome preview sent.' if ok else 'Welcome delivery failed. Check the configured channel and bot permissions.')


@bot.tree.command(description='Post or refresh the public Vynex community dashboard.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def dashboard(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    message = await bot.dashboard.ensure_dashboard()
    await reply(i, f'Community dashboard ready: {message.jump_url}')


@bot.tree.command(description='Send a test event to the configured staff logs channel.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def logtest(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    ok = await bot.event_logs.send('Logging test', f'Requested by user {i.user.id}. Staff event logging is connected.')
    await reply(i, 'Test sent to the staff logs channel.' if ok else bot.event_logs.last_error)


@bot.tree.command(description='Post or refresh the Components V2 community rules.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def rules(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    messages = await bot.rules.ensure_rules()
    await reply(i, f'Community rules refreshed: {messages[0].jump_url}')


@bot.tree.command(description='Choose an app and generate one private access key.')
@app_commands.guild_only()
@app_commands.check(key_staff)
@app_commands.checks.cooldown(1, 5)
@app_commands.describe(package='Choose which application this key unlocks.')
@app_commands.choices(package=[
    app_commands.Choice(name='Vynex Tweaks', value='tweaks'),
    app_commands.Choice(name='VYNEX Premium Package', value='premium'),
])
async def generate(i: discord.Interaction, package: app_commands.Choice[str]):
    await i.response.defer(ephemeral=True)
    application = package.value
    app_name = {'tweaks': 'Vynex Tweaks', 'premium': 'VYNEX Premium Package'}[application]
    key = await vynex.generate(application)
    logged = await bot.event_logs.key_generated(i, app_name, key)
    await reply(i, f'## Generated 1 {app_name} key\n**Expiry:** Lifetime\n**App:** {app_name}\n'
        f'**Key:**\n```{key}```\n**Activation:** Sign in to {app_name}, verify your email, and enter this key in the app.\n'
        f'-# Requested by {discord.utils.escape_markdown(i.user.display_name)} • Copy this key and keep it private.')
    if not logged:
        await reply(i, 'Key generated, but its staff log could not be delivered. Check the logs channel permissions.')


@bot.tree.command(description='Record a warning for a member.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(i: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 500]):
    target_check(i, member)
    with database() as db:
        db.execute('INSERT INTO warnings(guild,member,moderator,reason) VALUES(?,?,?,?)',
                   (i.guild_id, member.id, i.user.id, reason))
    await reply(i, f'Warning saved for {member.display_name}.')


@bot.tree.command(description='View a member’s latest 10 warnings and total count.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(i: discord.Interaction, member: discord.Member):
    with database() as db:
        rows = db.execute('SELECT * FROM warnings WHERE guild=? AND member=? ORDER BY id DESC LIMIT 10',
                          (i.guild_id, member.id)).fetchall()
        count = db.execute('SELECT COUNT(*) FROM warnings WHERE guild=? AND member=?', (i.guild_id, member.id)).fetchone()[0]
    text = f'## Warnings: {count}\n'
    for row in rows:
        text += f"\n**#{row['id']} • {row['created']} UTC**\n{discord.utils.escape_markdown(row['reason'])}\n"
    await reply(i, text)


@bot.tree.command(description='Timeout a member for up to 28 days.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def timeout(i: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: app_commands.Range[str, 1, 400] = 'No reason provided'):
    target_check(i, member)
    if member.guild_permissions.administrator:
        raise app_commands.CheckFailure('Administrators cannot be timed out.')
    await i.response.defer(ephemeral=True)
    await member.timeout(timedelta(minutes=minutes), reason=audit(i, reason))
    await reply(i, f'{member.display_name} timed out for {minutes} minutes.')


@bot.tree.command(description='Remove a member’s timeout.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
async def untimeout(i: discord.Interaction, member: discord.Member):
    target_check(i, member)
    await i.response.defer(ephemeral=True)
    await member.timeout(None, reason=audit(i, 'Remove timeout'))
    await reply(i, 'Timeout removed.')


@bot.tree.command(description='Kick a member from the server.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
async def kick(i: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 400] = 'No reason provided'):
    target_check(i, member)
    await i.response.defer(ephemeral=True)
    await member.kick(reason=audit(i, reason))
    await reply(i, f'{member.display_name} kicked.')


@bot.tree.command(description='Ban a member without deleting their message history.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def ban(i: discord.Interaction, member: discord.Member, reason: app_commands.Range[str, 1, 400] = 'No reason provided'):
    target_check(i, member)
    await i.response.defer(ephemeral=True)
    await member.ban(reason=audit(i, reason), delete_message_seconds=0)
    await reply(i, f'{member.display_name} banned.')


@bot.tree.command(description='Unban a user by their Discord user ID.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
async def unban(i: discord.Interaction, user_id: str):
    if not user_id.isdecimal() or not 0 < int(user_id) < 2**64:
        return await reply(i, 'Enter a valid numeric Discord user ID.')
    await i.response.defer(ephemeral=True)
    await i.guild.unban(discord.Object(id=int(user_id)), reason=audit(i, 'Unban'))
    await reply(i, 'User unbanned.')


@bot.tree.command(description='Delete up to 100 recent messages in this channel.')
@app_commands.guild_only()
@app_commands.check(server_only)
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
async def clear(i: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not isinstance(i.channel, (discord.TextChannel, discord.Thread)):
        return await reply(i, 'Use this in a text channel or thread.')
    await i.response.defer(ephemeral=True)
    deleted = await i.channel.purge(limit=amount, before=i.created_at, reason=audit(i, 'Message cleanup'))
    await reply(i, f'Deleted {len(deleted)} messages.')


@bot.tree.error
async def error_handler(i: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, 'original', error)
    command = getattr(getattr(i, 'command', None), 'name', None) or (getattr(i, 'data', None) or {}).get('name', 'unknown')
    reference = getattr(i, 'id', 'unknown')
    logging.error('Command /%s failed: %s; HTTP=%s code=%s; reference=%s', command,
        type(original).__name__, getattr(original, 'status', '-'), getattr(original, 'code', '-'), reference)
    if isinstance(original, VynexError):
        message = str(original)
    elif isinstance(original, app_commands.CommandOnCooldown):
        message = f'Try again in {original.retry_after:.0f} seconds.'
    elif isinstance(original, app_commands.CheckFailure):
        message = str(original)
    elif isinstance(original, discord.Forbidden):
        message = 'Discord refused this action. Check the bot’s permissions and role position.'
    elif isinstance(original, discord.NotFound):
        message = 'Discord could not find that member, ban, or message.'
    elif isinstance(original, app_commands.CommandSignatureMismatch):
        message = 'Discord has an outdated command definition. Reload Discord and choose the command again after the latest bot deployment finishes.'
    elif isinstance(original, app_commands.CommandNotFound):
        version = os.getenv('RENDER_GIT_COMMIT', 'unknown')[:7]
        message = f'This bot instance has not loaded /{command}. Running build: {version}. Wait for the latest deployment to finish, then reload Discord.'
    elif isinstance(original, discord.HTTPException):
        message = f'Discord rejected /{command} (HTTP {original.status}, code {original.code}). Reference: {reference}.'
    elif isinstance(original, RuntimeError):
        message = f'/{command} could not run: {original}'
    else:
        logging.error('Command failed', exc_info=(type(original), original, original.__traceback__))
        message = f'/{command} failed ({type(original).__name__}). Reference: {reference}. Send staff the Render error for this reference.'
    await reply(i, message)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise SystemExit('Set DISCORD_TOKEN in .env first.')
    bot.run(token)
