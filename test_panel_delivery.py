import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import discord
from dashboard import DashboardView
from tickets import TicketPanel
from panel_style import publish_panel


class PanelDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_gallery_images_are_uploaded_on_send_and_replaced_on_edit(self):
        for kind, view in (('community', DashboardView(NS())), ('support', TicketPanel(NS()))):
            for editing in (False, True):
                channel = NS(send=AsyncMock())
                message = NS(edit=AsyncMock()) if editing else None
                sender = message.edit if editing else channel.send
                captured = []
                async def inspect(**kwargs):
                    files = kwargs['attachments' if editing else 'files']
                    captured.extend(files)
                    expected = {item['media']['url'].removeprefix('attachment://')
                                for component in view.to_components()[0]['components'] if component['type'] == 12
                                for item in component['items']}
                    self.assertEqual(expected, {f.filename for f in files})
                    self.assertTrue(all(f.fp.read(8) == b'\x89PNG\r\n\x1a\n' for f in files))
                    self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'], [])
                sender.side_effect = inspect
                await publish_panel(channel, view, kind, message=message)
                self.assertTrue(all(f.fp.closed for f in captured))

    async def test_upload_failure_closes_files_and_preserves_the_original_message(self):
        captured = []
        async def failed(**kwargs):
            captured.extend(kwargs['attachments'])
            raise discord.Forbidden(NS(status=403, reason='Forbidden'), 'cannot upload')
        channel = NS(send=AsyncMock()); message = NS(edit=AsyncMock(side_effect=failed))
        with self.assertRaises(discord.Forbidden):
            await publish_panel(channel, DashboardView(NS()), 'community', message=message)
        self.assertTrue(all(f.fp.closed for f in captured))
        channel.send.assert_not_called()
