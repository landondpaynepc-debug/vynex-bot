"""Calls the existing Vynex API; never creates local substitute keys."""
import asyncio
import re
from urllib.parse import urlsplit

import aiohttp


class VynexError(Exception):
    pass


class VynexClient:
    def __init__(self, base_url: str, password: str):
        self.base_url = base_url.strip().rstrip('/')
        self.password = password
        url = urlsplit(self.base_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError('VYNEX_API_URL must be the HTTPS origin of your Vynex service, such as https://your-service.onrender.com.')
        if not password:
            raise ValueError('Set VYNEX_ADMIN_PASSWORD to the existing administrator password from your Vynex Render service.')

    async def appeals_request(self, path, body=None):
        """Only the existing API origin receives the administrator credential."""
        if path not in ('/v1/admin/appeals/invite', '/v1/admin/appeals/ack', '/v1/admin/appeals/pending'):
            raise ValueError('Unknown appeals operation.')
        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request('GET' if path.endswith('/pending') else 'POST', self.base_url+path,
                        headers={'X-Admin-Password':self.password}, allow_redirects=False,
                        **({'params':body} if path.endswith('/pending') else {'json':body})) as response:
                    if response.status != 200:
                        raise VynexError(f'Appeals service returned HTTP {response.status}.')
                    result = await response.json()
                    if not isinstance(result, dict) or result.get('ok') is not True:
                        raise VynexError('Unexpected appeals response.')
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise VynexError('Appeals service could not be reached.') from None

    async def appeal_link(self, guild_id, user_id, case_id, issued_at):
        result = await self.appeals_request('/v1/admin/appeals/invite',
            {'guild_id':str(guild_id), 'user_id':str(user_id), 'case_id':case_id, 'issued_at':issued_at.isoformat()})
        token = result.get('token', '')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', token):
            raise VynexError('Invalid appeal invitation response.')
        url = self.base_url + '/appeal#token=' + token
        if len(url) > 512:
            raise VynexError('Appeal link is too long for Discord.')
        return url

    async def generate(self, application: str):
        if application not in ('tweaks', 'premium', 'overclock'):
            raise VynexError('Choose Vynex Tweaks, Premium or Overclock Bundle.')
        timeout = aiohttp.ClientTimeout(total=90, connect=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.base_url + '/v1/admin/generate-keys',
                    headers={'X-Admin-Password': self.password, 'X-Vynex-App': application},
                    json={'count': 1}, allow_redirects=False,
                ) as response:
                    if response.status == 401:
                        raise VynexError('Vynex rejected the administrator password. Check the bot’s VYNEX_ADMIN_PASSWORD setting.')
                    if response.status != 200:
                        raise VynexError(f'Vynex returned HTTP {response.status}. No key was displayed; check the service before generating again.')
                    if response.headers.get('X-Vynex-App') != application:
                        raise VynexError('The API did not confirm the selected app. Check its deployment before generating again.')
                    payload = await response.json()
                    keys = payload.get('keys') if isinstance(payload, dict) else None
                    if (not isinstance(payload, dict) or payload.get('ok') is not True or not isinstance(keys, list) or len(keys) != 1
                            or not isinstance(keys[0], str)
                            or not re.fullmatch(r'VYNEX-(?:[0-9A-F]{4}-){2}[0-9A-F]{4}', keys[0])):
                        raise VynexError('Vynex returned an unexpected key response. Check the API before generating again.')
                    return keys[0]
        except VynexError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            # Do not log response bodies or exception details: they may contain secrets.
            # No automatic retries: the API has no idempotency support.
            raise VynexError('Could not confirm key generation with Vynex. A key may have been saved; check the service before trying again.') from None
