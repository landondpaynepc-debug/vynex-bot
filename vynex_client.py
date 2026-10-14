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

    async def generate(self, application: str):
        if application not in ('tweaks', 'premium'):
            raise VynexError('Choose Vynex Tweaks or VYNEX Premium Package.')
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
