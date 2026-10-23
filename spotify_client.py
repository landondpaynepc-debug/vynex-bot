"""Private per-user Spotify device controls backed by the Vynex API."""
import asyncio
from urllib.parse import urlsplit

import aiohttp
import discord

from ui_messages import TICKET_COLOR, text_view


class SpotifyError(RuntimeError):
    pass


class SpotifyClient:
    def __init__(self, base_url, password):
        self.base_url, self.password = base_url, password

    async def request(self, user_id, action, device=None):
        payload = {'discord_id':str(user_id)}
        endpoint = '/v1/spotify/connect' if action == 'link' else '/v1/spotify/action'
        if action != 'link':
            payload.update(action=action, device=device)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
                async with session.post(self.base_url + endpoint, json=payload,
                        headers={'X-Admin-Password':self.password}, allow_redirects=False) as response:
                    data = await response.json()
                    if response.status == 404:
                        raise SpotifyError('Spotify linking is not deployed on the API yet.')
                    if response.status != 200:
                        message = data.get('message') or data.get('detail')
                        raise SpotifyError(message if isinstance(message, str) else 'Spotify could not complete this action.')
                    if data.get('ok') is not True:
                        raise SpotifyError('Spotify returned an unexpected response.')
                    if action == 'link':
                        parsed = urlsplit(data.get('url', ''))
                        if parsed.scheme != 'https' or parsed.netloc != 'accounts.spotify.com' or parsed.path != '/authorize':
                            raise SpotifyError('Spotify returned an invalid sign-in URL.')
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise SpotifyError('Spotify connection is temporarily unavailable. Please try again.') from None


class SpotifyButton(discord.ui.Button):
    def __init__(self, client, owner, label, action):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.client, self.owner, self.action = client, owner, action

    async def callback(self, interaction):
        if interaction.user.id != self.owner:
            return await interaction.response.send_message(view=text_view('Use /spotify to open your own controls.'), ephemeral=True)
        await interaction.response.send_message(view=text_view('Contacting your Spotify device…'), ephemeral=True)
        try:
            data = await self.client.request(self.owner, self.action)
            view = SpotifyPanel(self.client, self.owner, self.action, data)
        except SpotifyError as error:
            view = text_view(str(error))
        await interaction.edit_original_response(view=view, allowed_mentions=discord.AllowedMentions.none())


class SpotifyPanel(discord.ui.LayoutView):
    def __init__(self, client, owner, action, data):
        super().__init__(timeout=300)
        if action == 'link':
            text = ('## Connect your Spotify account\nSign in using the button below and approve the requested playback permissions. '
                    'This private link expires in 10 minutes.\n\nPlayback happens on your Spotify devices and requires Premium.')
            row = discord.ui.ActionRow(discord.ui.Button(label='Sign in with Spotify',
                style=discord.ButtonStyle.link, url=data['url']))
        else:
            row = discord.ui.ActionRow(*(SpotifyButton(client, owner, label, value) for label, value in
                [('Status', 'status'), ('Resume', 'play'), ('Pause', 'pause'), ('Next', 'next'), ('Previous', 'previous')]))
            if action == 'status':
                track = discord.utils.escape_markdown(data.get('track') or 'Nothing currently playing')
                artist = discord.utils.escape_markdown(data.get('artists') or '')
                device = discord.utils.escape_markdown(data.get('device') or 'No active device')
                text = f'## Your Spotify\n**Track:** {track}\n**Artist:** {artist}\n**Device:** {device}\n'
                text += '**State:** ' + ('Playing' if data.get('is_playing') else 'Paused / inactive')
            elif action == 'devices':
                devices = data.get('devices', [])
                text = '## Your Spotify devices\n' + ('\n\n'.join(
                    f'**{discord.utils.escape_markdown((device.get("name") or "Device")[:80])}** '
                    f'{"(active)" if device.get("is_active") else ""}\nID: `{device.get("id") or "Unavailable"}`'
                    for device in devices[:10]) or 'Open Spotify on a phone or computer and start a song to make it available.')
                text += '\n\nUse `/spotify action:Select device device:ID` to choose one.'
            else:
                text = '## Your Spotify\n' + data.get('message', 'Done.')
        self.add_item(discord.ui.Container(discord.ui.TextDisplay(text), discord.ui.Separator(visible=False),
                                          row, accent_colour=TICKET_COLOR))
