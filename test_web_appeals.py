from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

import discord
from test_appeals import fixture, stream, CASE, ANSWERS
from appeals import AppealManager, invitation_view
from vynex_client import VynexClient, VynexError


class WebAppealTests(unittest.IsolatedAsyncioTestCase):
    def setup_case(self):
        f = fixture()
        f.guild.fetch_ban.return_value = NS(user=NS(id=42))
        record = dict(guild_id='10',user_id='42',case_id=CASE,answers=ANSWERS,issued_at=discord.utils.utcnow().isoformat())
        f.api = NS(base_url='https://example.invalid', appeal_link=AsyncMock(return_value='https://example.invalid/appeal#token=fixture'),
                   appeals_request=AsyncMock(return_value={'ok':True,'appeals':[record]}))
        f.manager = AppealManager(f.bot, 10, f.api)
        original = f.channel.send.side_effect
        async def send(**kw):
            message = await original(**kw); message.id = 555; return message
        f.channel.send.side_effect = send
        return f

    async def test_web_link_is_available_before_ban_without_an_interaction(self):
        f = self.setup_case()
        await f.manager.notify_ban(f.guild, f.user, before_ban=True)
        nodes = f.user.send.call_args.kwargs['view'].to_components()[0]['components'][-1]['components']
        self.assertEqual(nodes[0]['style'],5)
        self.assertEqual(nodes[0]['url'],'https://example.invalid/appeal#token=fixture')
        self.assertNotIn('custom_id',nodes[0])

    async def test_delivery_checks_ban_posts_then_acknowledges_and_deduplicates(self):
        f = self.setup_case()
        await f.manager.deliver_pending()
        f.channel.send.assert_awaited_once()
        ack = f.api.appeals_request.call_args.args
        self.assertEqual(ack[0],'/v1/admin/appeals/ack')
        self.assertEqual(ack[1]['message_id'],'555')
        self.assertEqual(ack[1]['status'],'delivered')
        self.assertEqual(f.channel.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'],[])
        await f.manager.deliver_pending()
        f.channel.send.assert_awaited_once()

    async def test_failed_discord_delivery_is_not_acknowledged(self):
        f = self.setup_case()
        f.channel.send.side_effect = OSError('unavailable')
        with self.assertRaises(OSError): await f.manager.deliver_pending()
        f.api.appeals_request.assert_awaited_once()

    async def test_unbanned_account_is_not_forwarded(self):
        f = self.setup_case()
        f.guild.fetch_ban.side_effect = discord.NotFound(NS(status=404,reason='Not Found'),'no ban')
        await f.manager.deliver_pending()
        f.channel.send.assert_not_called()
        self.assertEqual(f.api.appeals_request.call_args.args[1]['status'],'not_banned')

    async def test_old_invitation_is_edited_with_web_link_without_a_new_dm(self):
        f = self.setup_case()
        view = invitation_view(f.guild,42,CASE)
        message = NS(author=f.me,created_at=discord.utils.utcnow(),edit=AsyncMock(),
                     components=[NS(to_dict=lambda: view.to_components()[0])])
        dm = NS(history=lambda **kw: stream([message]))
        f.user.create_dm = AsyncMock(return_value=dm)
        f.guild.bans = lambda **kw: stream([NS(user=f.user)])
        await f.manager.repair_invitations()
        message.edit.assert_awaited_once()
        self.assertIn('https://example.invalid/appeal#token=fixture',str(message.edit.call_args.kwargs['view'].to_components()))
        f.user.send.assert_not_called()

    async def test_invite_service_failure_does_not_prevent_ban_notification(self):
        f = self.setup_case(); f.api.appeal_link.side_effect = VynexError('offline')
        self.assertTrue(await f.manager.notify_ban(f.guild,f.user,before_ban=True))
        f.user.send.assert_awaited_once()
