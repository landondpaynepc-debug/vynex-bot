import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from test_tickets import fixture, stream
from tickets import TicketControls, TicketManager, CLAIM_ID, ticket_info, ticket_claim


def staff(f, ident, admin=False):
    member = MagicMock(spec=discord.Member)
    member.id = ident; member.roles = [f.staff]
    member.guild_permissions = NS(administrator=admin)
    return member


def control_message(f, claimed_by=None):
    view = TicketControls(f.manager, claimed_by=claimed_by)
    return NS(author=f.me, edit=AsyncMock(),
              components=[NS(to_dict=lambda: view.to_components()[0])])


async def prepared():
    f = fixture()
    await f.manager.open_ticket(f.interaction(), 'general')
    f.channel = f.channels[0]
    f.guild.fetch_channel = AsyncMock(return_value=f.channel)
    async def edit(**kwargs):
        if 'topic' in kwargs: f.channel.topic = kwargs['topic']
        return f.channel
    f.channel.edit.side_effect = edit
    f.request = f.interaction(f.channel, staff(f, 123))
    f.request.message = control_message(f)
    return f


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_claim_is_saved_and_shown_without_extra_pings(self):
        f = await prepared()
        await f.manager.claim_ticket(f.request)
        self.assertEqual(ticket_claim(f.channel), 123)
        self.assertEqual(ticket_info(f.channel), (42, 'general'))
        payload = f.request.message.edit.call_args.kwargs
        self.assertIn('<@123>', str(payload['view'].to_components()))
        self.assertEqual(payload['allowed_mentions'].to_dict()['parse'], [])
        self.assertTrue(payload['view'].is_persistent())
        self.assertIn('Release Claim', str(payload['view'].to_components()))

    async def test_non_staff_owner_and_other_server_cannot_claim(self):
        f = await prepared()
        f.request.user = f.owner
        await f.manager.claim_ticket(f.request)
        f.channel.edit.assert_not_called()
        f.request.user = staff(f, 123); f.request.guild_id = 11
        await f.manager.claim_ticket(f.request)
        f.channel.edit.assert_not_called()

    async def test_simultaneous_claims_have_one_winner_and_stale_click_does_not_release(self):
        f = await prepared()
        second = f.interaction(f.channel, staff(f, 456)); second.message = control_message(f)
        await asyncio.gather(f.manager.claim_ticket(f.request), f.manager.claim_ticket(second))
        self.assertIn(ticket_claim(f.channel), (123, 456))
        f.channel.edit.assert_awaited_once()
        await f.manager.claim_ticket(f.request)
        f.channel.edit.assert_awaited_once()

    async def test_only_claimant_or_admin_can_release(self):
        for ident, admin, allowed in ((123, False, True), (456, False, False), (456, True, True)):
            f = await prepared()
            f.channel.topic += ';claimed=123'
            f.request.user = staff(f, ident, admin)
            f.request.message = control_message(f, 123)
            await f.manager.claim_ticket(f.request)
            self.assertEqual(ticket_claim(f.channel), None if allowed else 123)

    async def test_failed_save_does_not_show_claim_as_successful(self):
        f = await prepared()
        f.channel.edit.side_effect = discord.Forbidden(NS(status=403, reason='Forbidden'), 'cannot edit')
        await f.manager.claim_ticket(f.request)
        self.assertIsNone(ticket_claim(f.channel))
        f.request.message.edit.assert_not_called()
        self.assertIn('could not be confirmed', str(f.request.followup.send.call_args.kwargs['view'].to_components()))

    async def test_claim_survives_restart_and_owner_can_still_close(self):
        f = await prepared()
        await f.manager.claim_ticket(f.request)
        manager = TicketManager(f.bot, f.guild.id, f.staff.id)
        message = control_message(f)
        f.channel.history = lambda **kw: stream([message])
        f.bot.get_guild = lambda ident: f.guild
        await manager.refresh_open_tickets()
        self.assertIn('<@123>', str(message.edit.call_args.kwargs['view'].to_components()))
        self.assertTrue(manager.can_close(f.owner, f.channel, f.guild.id))
        await manager.open_ticket(f.interaction(), 'general')
        f.guild.create_text_channel.assert_awaited_once()

    async def test_deleted_or_unrelated_channel_is_not_claimed(self):
        f = await prepared()
        f.channel.topic = 'unrelated channel'
        await f.manager.claim_ticket(f.request)
        f.channel.edit.assert_not_called()
        f.guild.fetch_channel.side_effect = discord.NotFound(NS(status=404, reason='Not Found'), 'deleted')
        await f.manager.claim_ticket(f.request)
        f.channel.edit.assert_not_called()


if __name__ == '__main__': unittest.main()
