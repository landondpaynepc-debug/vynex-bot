import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import discord
from discord import app_commands
from spotify_client import SpotifyClient, SpotifyPanel, SpotifyError, SpotifyButton


class SpotifyClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_command_uses_invoking_user_only(self):
        source = ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
        function = next(n for n in source.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='spotify')
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        async def check(i): return True
        spotify = NS(request=AsyncMock(return_value={'ok':True, 'message':'Paused'}))
        from ui_messages import text_view
        scope = dict(discord=discord, app_commands=app_commands, bot=NS(tree=tree,spotify=spotify),
            server_only=check, text_view=text_view, SpotifyPanel=SpotifyPanel, SpotifyError=SpotifyError)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'spotify-command-test','exec'),scope)
        request = NS(user=NS(id=42), response=NS(send_message=AsyncMock()), edit_original_response=AsyncMock())
        await tree.get_command('spotify').callback(request, app_commands.Choice(name='Pause',value='pause'))
        spotify.request.assert_awaited_once_with(42,'pause',None)
        self.assertTrue(request.response.send_message.call_args.kwargs['ephemeral'])
        self.assertEqual(request.edit_original_response.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        await client.close()

    async def test_other_users_cannot_use_account_buttons(self):
        client = NS(request=AsyncMock())
        request = NS(user=NS(id=77), response=NS(send_message=AsyncMock()))
        button = SpotifyButton(client,42,'Pause','pause')
        await button.callback(request)
        client.request.assert_not_called()
        self.assertTrue(request.response.send_message.call_args.kwargs['ephemeral'])

    async def test_status_and_login_use_gray_v2_panels(self):
        from ui_messages import TICKET_COLOR
        for action, data in [('status',{'track':'Song','artists':'Artist','device':'Phone','is_playing':True}),
                ('link',{'url':'https://accounts.spotify.com/authorize?state=example'})]:
            view=SpotifyPanel(NS(),42,action,data)
            self.assertTrue(view.has_components_v2())
            self.assertEqual(view.to_components()[0]['accent_color'],TICKET_COLOR)

    async def test_client_authenticates_without_sending_spotify_tokens(self):
        calls=[]
        class Response:
            status=200
            async def json(self): return {'ok':True,'message':'Paused'}
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        class Session:
            def __init__(self,**kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def post(self,url,**kwargs): calls.append((url,kwargs));return Response()
        with patch('spotify_client.aiohttp.ClientSession',Session):
            await SpotifyClient('https://example.invalid','offline-admin').request(42,'pause')
        self.assertEqual(calls[0][1]['json']['discord_id'],'42')
        self.assertEqual(calls[0][1]['headers']['X-Admin-Password'],'offline-admin')
        self.assertNotIn('access_token',str(calls))
