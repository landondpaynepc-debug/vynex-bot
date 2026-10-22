import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from welcome import WelcomeManager, AUTO_ROLE_ID


def fixture():
    role = MagicMock(spec=discord.Role)
    role.id = AUTO_ROLE_ID
    role.managed = False
    role.is_default.return_value = False
    role.__ge__.return_value = False
    me = NS(guild_permissions=NS(manage_roles=True), top_role=NS())
    guild = NS(id=10, me=me, get_role=lambda ident: role, fetch_roles=AsyncMock(return_value=[role]))
    member = NS(id=42, guild=guild, roles=[], add_roles=AsyncMock())
    manager = WelcomeManager(NS(get_guild=lambda ident: guild), 10)
    return manager, member, role


class AutoRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_assigns_exact_role_and_preserves_existing_roles(self):
        manager, member, role = fixture()
        member.roles = [NS(id=1)]
        await manager.check_auto_role()
        self.assertTrue(await manager.assign_role(member))
        member.add_roles.assert_awaited_once_with(role, reason='Vynex automatic role for new server member', atomic=True)

    async def test_other_servers_and_existing_role_are_not_modified(self):
        manager, member, role = fixture()
        member.guild.id = 20
        self.assertFalse(await manager.assign_role(member))
        member.guild.id = 10
        member.roles = [role]
        self.assertTrue(await manager.assign_role(member))
        member.add_roles.assert_not_called()

    async def test_missing_permissions_or_high_role_fail_without_crashing(self):
        for failure in ('permission', 'hierarchy', 'managed', 'missing'):
            manager, member, role = fixture()
            if failure == 'permission': member.guild.me.guild_permissions.manage_roles = False
            if failure == 'hierarchy': role.__ge__.return_value = True
            if failure == 'managed': role.managed = True
            if failure == 'missing':
                member.guild.get_role = lambda ident: None
                member.guild.fetch_roles = AsyncMock(return_value=[])
            with patch('welcome.logging.error'):
                self.assertFalse(await manager.assign_role(member))
            member.add_roles.assert_not_called()
