import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from appeals import (AppealManager, AppealButton, AppealModal, invitation_view,
                     APPEAL_CHANNEL_ID, CASE_PATTERN, QUESTIONS)

CASE = 'a' * 24
ANSWERS = ['My explanation of what happened.', 'Why I am asking for another chance.',
           'How I will follow the server rules.', '']


async def stream(values):
    for value in values:
        yield value


def sent_text(sender):
    return sender.call_args.kwargs['view'].to_components()[0]['components'][0]['content']


def fixture():
    me = NS(id=99, guild_permissions=NS(ban_members=True))
    user = NS(id=42, bot=False, send=AsyncMock())
    guild = NS(id=10, name='Vynex', me=me, fetch_ban=AsyncMock())
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = APPEAL_CHANNEL_ID; channel.guild = guild
    channel.permissions_for.return_value = NS(view_channel=True, send_messages=True,
                                              embed_links=True, read_message_history=True)
    messages = []
    async def send(**kw):
        message = NS(author=me, embeds=[kw['embed']])
        messages.append(message)
        return message
    channel.send = AsyncMock(side_effect=send)
    channel.history = lambda **kw: stream(messages)
    bot = NS(user=me, get_channel=lambda ident: channel, get_guild=lambda ident: guild,
             event_logs=NS(send=AsyncMock()), add_dynamic_items=MagicMock())
    manager = AppealManager(bot, guild.id)
    def interaction():
        return NS(user=user, guild_id=None, client=NS(appeals=manager),
                  message=NS(author=me, created_at=discord.utils.utcnow()),
                  response=NS(send_modal=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock()),
                  followup=NS(send=AsyncMock()))
    return NS(bot=bot, manager=manager, guild=guild, user=user, me=me, channel=channel,
              messages=messages, interaction=interaction)


class AppealTests(unittest.IsolatedAsyncioTestCase):
    async def test_persistent_button_reconstructs_after_restart_and_modal_limits(self):
        f = fixture()
        f.manager.register_view()
        f.bot.add_dynamic_items.assert_called_once_with(AppealButton)
        view = invitation_view(f.guild, 42, CASE)
        self.assertTrue(view.is_persistent())
        custom_id = view.to_components()[0]['components'][1]['components'][0]['custom_id']
        self.assertLessEqual(len(custom_id), 100)
        button = await AppealButton.from_custom_id(None, None, re.fullmatch(CASE_PATTERN, custom_id))
        request = f.interaction()
        await button.callback(request)
        modal = request.response.send_modal.call_args.args[0]
        self.assertIsInstance(modal, AppealModal)
        self.assertEqual(len(modal.children), 4)
        self.assertEqual([c.required for c in modal.children], [True, True, True, False])
        self.assertTrue(all(c.max_length == 1000 and len(c.label) <= 45 for c in modal.children))

    async def test_preban_and_gateway_event_send_only_one_invitation(self):
        f = fixture()
        results = await asyncio.gather(f.manager.notify_ban(f.guild, f.user, before_ban=True),
                                       f.manager.notify_ban(f.guild, f.user))
        self.assertEqual(results, [True, True])
        f.user.send.assert_awaited_once()
        self.assertIn('only if the ban is applied', sent_text(f.user.send))
        self.assertEqual(f.user.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        f.manager.forget(f.guild, f.user)
        await f.manager.notify_ban(f.guild, f.user)
        self.assertEqual(f.user.send.await_count, 2)

    async def test_closed_dms_report_to_staff_without_raising(self):
        f = fixture()
        f.user.send.side_effect = discord.Forbidden(NS(status=403, reason='Forbidden'), 'closed DMs')
        self.assertFalse(await f.manager.notify_ban(f.guild, f.user))
        f.bot.event_logs.send.assert_awaited_once()
        self.assertFalse(await f.manager.notify_ban(f.guild, f.user))
        f.user.send.assert_awaited_once()

    async def test_wrong_server_and_bot_accounts_are_ignored(self):
        f = fixture()
        self.assertFalse(await f.manager.notify_ban(NS(id=11), f.user))
        f.user.bot = True
        self.assertFalse(await f.manager.notify_ban(f.guild, f.user))
        f.user.send.assert_not_called()

    async def test_modal_rejects_other_user_server_or_untrusted_message(self):
        for field in ('user', 'guild', 'author', 'case', 'server'):
            f = fixture(); request = f.interaction()
            case, guild_id = CASE, 10
            if field == 'user': request.user = NS(id=123)
            if field == 'guild': request.guild_id = 10
            if field == 'author': request.message.author = NS(id=123)
            if field == 'case': case = 'invalid'
            if field == 'server': guild_id = 11
            await f.manager.open_form(request, guild_id, 42, case)
            request.response.send_modal.assert_not_called()
            request.response.send_message.assert_awaited_once()

    async def test_submission_sends_all_answers_to_exact_channel_without_mentions(self):
        f = fixture(); request = f.interaction()
        await f.manager.submit(request, 42, CASE, request.message.created_at, ANSWERS)
        request.response.defer.assert_awaited_once()
        f.guild.fetch_ban.assert_awaited_once()
        self.assertEqual(f.guild.fetch_ban.call_args.args[0].id, 42)
        f.channel.send.assert_awaited_once()
        data = f.channel.send.call_args.kwargs
        self.assertEqual(f.channel.id, 1542759018462715924)
        self.assertEqual([v.name for v in data['embed'].fields], [q for q, _ in QUESTIONS])
        self.assertEqual([v.value for v in data['embed'].fields][:3], ANSWERS[:3])
        self.assertIn('42', data['embed'].description)
        self.assertEqual(data['allowed_mentions'].to_dict()['parse'], [])
        self.assertIn('was submitted', sent_text(request.followup.send))

    async def test_parallel_submissions_and_restart_do_not_duplicate_appeal(self):
        f = fixture(); request = f.interaction(); second = f.interaction()
        await asyncio.gather(f.manager.submit(request, 42, CASE, request.message.created_at, ANSWERS),
                             f.manager.submit(second, 42, CASE, request.message.created_at, ANSWERS))
        f.channel.send.assert_awaited_once()
        restarted = AppealManager(f.bot, 10)
        retry = f.interaction()
        await restarted.submit(retry, 42, CASE, request.message.created_at, ANSWERS)
        f.channel.send.assert_awaited_once()
        self.assertIn('already been submitted', sent_text(retry.followup.send))

    async def test_non_banned_user_cannot_submit(self):
        f = fixture(); request = f.interaction()
        f.guild.fetch_ban.side_effect = discord.NotFound(NS(status=404, reason='Not Found'), 'not banned')
        await f.manager.submit(request, 42, CASE, request.message.created_at, ANSWERS)
        f.channel.send.assert_not_called()
        self.assertIn('not currently banned', sent_text(request.followup.send))

    async def test_invalid_answers_rejected_before_any_network_call(self):
        for answers in (['short'] * 4, ANSWERS[:2], ['x' * 1001] * 4):
            f = fixture(); request = f.interaction()
            await f.manager.submit(request, 42, CASE, request.message.created_at, answers)
            f.guild.fetch_ban.assert_not_called()
            f.channel.send.assert_not_called()

    async def test_send_failure_is_not_reported_as_success_and_retry_checks_history(self):
        f = fixture(); request = f.interaction()
        original_send = f.channel.send.side_effect
        async def uncertain_send(**kwargs):
            await original_send(**kwargs)
            raise OSError('simulated lost response after Discord saved the message')
        f.channel.send.side_effect = uncertain_send
        await f.manager.submit(request, 42, CASE, request.message.created_at, ANSWERS)
        self.assertIn('could not be confirmed', sent_text(request.followup.send))
        await f.manager.submit(f.interaction(), 42, CASE, request.message.created_at, ANSWERS)
        f.channel.send.assert_awaited_once()

    async def test_channel_permission_or_ban_lookup_failure_does_not_accept(self):
        for fail in ('permission', 'ban lookup', 'history'):
            f = fixture(); request = f.interaction()
            if fail == 'permission': f.channel.permissions_for.return_value.embed_links = False
            if fail == 'ban lookup': f.guild.fetch_ban.side_effect = OSError('unavailable')
            if fail == 'history': f.channel.history = MagicMock(side_effect=OSError('unavailable'))
            await f.manager.submit(request, 42, CASE, request.message.created_at, ANSWERS)
            f.channel.send.assert_not_called()
            self.assertIn('could not be confirmed', sent_text(request.followup.send))

    async def test_mod_command_sends_invitation_before_banning_and_preserves_failure(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        function = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'ban')
        function.decorator_list = []
        function.returns = None
        for argument in function.args.args: argument.annotation = None
        f = fixture(); events = []
        async def invite(*args, **kwargs): events.append('invite'); return False
        async def do_ban(**kwargs): events.append('ban')
        f.manager.notify_ban = AsyncMock(side_effect=invite)
        f.bot.appeals = f.manager
        namespace = {'discord': discord, 'bot': f.bot, 'target_check': lambda *args: None,
                     'audit': lambda *args: 'test reason', 'reply': AsyncMock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'ban-test', 'exec'), namespace)
        member = NS(id=42, display_name='Fixture user', ban=AsyncMock(side_effect=do_ban))
        request = f.interaction(); request.guild = f.guild
        await namespace['ban'](request, member)
        self.assertEqual(events, ['invite', 'ban'])
        self.assertIn('could not be delivered', namespace['reply'].call_args.args[1])
        member.ban.side_effect = discord.Forbidden(NS(status=403, reason='Forbidden'), 'role too low')
        f.manager.forget = MagicMock()
        with self.assertRaises(discord.Forbidden): await namespace['ban'](request, member)
        f.manager.forget.assert_called_once_with(f.guild, member)


if __name__ == '__main__': unittest.main()
