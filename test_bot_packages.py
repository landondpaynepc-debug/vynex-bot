"""Offline checks: no Discord connection, messages or production keys."""
import ast
import asyncio
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

source=ast.parse(Path(__file__).with_name('bot.py').read_text(encoding='utf-8'))
client_source=ast.parse(Path(__file__).with_name('vynex_client.py').read_text(encoding='utf-8'))
client_class=next(n for n in client_source.body if isinstance(n,ast.ClassDef) and n.name=='VynexClient')
error_class=next(n for n in client_source.body if isinstance(n,ast.ClassDef) and n.name=='VynexError')

class Packages(unittest.IsolatedAsyncioTestCase):
    async def test_discord_registers_required_package_choices(self):
        import discord
        from discord import app_commands
        command=next(n for n in source.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='generate')
        async def staff_check(i): return True
        client=discord.Client(intents=discord.Intents.none())
        tree=app_commands.CommandTree(client)
        globals_={'discord':discord,'app_commands':app_commands,'bot':SimpleNamespace(tree=tree),'key_staff':staff_check}
        exec(compile(ast.Module(body=[command],type_ignores=[]),'discord-registration-test','exec'),globals_)
        option=tree.get_command('generate').to_dict(tree)['options'][0]
        self.assertTrue(option['required'])
        self.assertEqual([(c['name'],c['value']) for c in option['choices']],[('Vynex Tweaks','tweaks'),('VYNEX Premium Package','premium')])
        await client.close()

    async def test_generation_sends_selected_application_and_rejects_mismatch(self):
        requests=[]
        scope={'value':'tweaks'}
        class Response:
            status=200
            @property
            def headers(self): return {'X-Vynex-App':scope['value']}
            async def json(self): return {'ok':True,'keys':['VYNEX-ABCD-1234-5678']}
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
        class Session:
            def __init__(self,**kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def post(self,url,**kwargs): requests.append(kwargs);return Response()
        globals_={'aiohttp':SimpleNamespace(ClientTimeout=lambda **kw:None,ClientSession=Session,ClientError=OSError),'asyncio':asyncio,'re':re,'urlsplit':urlsplit}
        exec(compile(ast.Module(body=[error_class,client_class],type_ignores=[]),'bot-client-test','exec'),globals_)
        client=globals_['VynexClient']('https://example.invalid','offline-admin')
        for app in ('tweaks','premium'):
            scope['value']=app
            self.assertEqual(await client.generate(app),'VYNEX-ABCD-1234-5678')
            self.assertEqual(requests[-1]['headers']['X-Vynex-App'],app)
            self.assertEqual(requests[-1]['headers']['X-Admin-Password'],'offline-admin')
        scope['value']='tweaks'
        with self.assertRaisesRegex(globals_['VynexError'],'did not confirm'): await client.generate('premium')
        count=len(requests)
        with self.assertRaises(globals_['VynexError']): await client.generate('unknown')
        self.assertEqual(len(requests),count)

    async def test_slash_command_requires_package_and_preserves_staff_check(self):
        command=next(n for n in source.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='generate')
        self.assertEqual([a.arg for a in command.args.args],['i','package'])
        self.assertEqual(command.args.defaults,[])
        decorators=[ast.unparse(d) for d in command.decorator_list]
        self.assertIn('app_commands.check(key_staff)',decorators)
        choices=next(d for d in command.decorator_list if isinstance(d,ast.Call) and ast.unparse(d.func)=='app_commands.choices')
        values=[next(k.value.value for k in choice.keywords if k.arg=='value') for choice in choices.keywords[0].value.elts]
        self.assertEqual(values,['tweaks','premium'])
        self.assertIn('await vynex.generate(application)',ast.unparse(command))

if __name__=='__main__': unittest.main(verbosity=2)
