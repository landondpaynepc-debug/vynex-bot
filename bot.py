"""Premium license issuing and Discord moderation. Python 3.10+."""
import logging
import os
from pathlib import Path
import sqlite3
from datetime import timedelta

import discord
from vynex_client import VynexClient, VynexError
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
        super().__init__(intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


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
    if i.response.is_done():
        await i.followup.send(text, ephemeral=True, **kwargs)
    else:
        await i.response.send_message(text, ephemeral=True, **kwargs)


def target_check(i, member):
    if member.id in (i.user.id, bot.user.id, i.guild.owner_id):
        raise app_commands.CheckFailure('You cannot moderate yourself, this bot, or the server owner.')
    if i.user.id != i.guild.owner_id and member.top_role >= i.user.top_role:
        raise app_commands.CheckFailure('That member has an equal or higher role than you.')
    if member.top_role >= i.guild.me.top_role:
        raise app_commands.CheckFailure('Move the bot role above that member’s highest role.')


def audit(i, reason):
    return f'{i.user} ({i.user.id}): {reason}'[:512]


@bot.tree.command(description='Generate one private Vynex Tweaks Premium access key.')
@app_commands.guild_only()
@app_commands.check(key_staff)
@app_commands.checks.cooldown(1, 5)
async def generate(i: discord.Interaction):
    await i.response.defer(ephemeral=True)
    key = await vynex.generate()
    embed = discord.Embed(title='✅ Generated 1 Premium key', color=0x8B35EF)
    embed.add_field(name='Tier', value='Premium', inline=False)
    embed.add_field(name='Expiry', value='Lifetime', inline=False)
    embed.add_field(name='App', value=COMPANY[:1024], inline=False)
    embed.add_field(name='Key', value=f'```{key}```', inline=False)
    embed.add_field(name='Activation', value='Sign in to Vynex Tweaks, verify your email, and enter this key in the app.', inline=False)
    embed.set_footer(text=f'Requested by {i.user.display_name} • Copy this key and keep it private.')
    await reply(i, embed=embed)


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
    embed = discord.Embed(title=f'Warnings: {count}', color=0x8B35EF)
    for row in rows:
        embed.add_field(name=f"#{row['id']} • {row['created']} UTC", value=discord.utils.escape_markdown(row['reason']), inline=False)
    await reply(i, embed=embed)


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
    else:
        logging.error('Command failed', exc_info=(type(original), original, original.__traceback__))
        message = 'The command failed. Check the bot console for details.'
    await reply(i, message)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise SystemExit('Set DISCORD_TOKEN in .env first.')
    bot.run(token)
