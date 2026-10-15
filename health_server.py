"""Small HTTP health server for running the Discord bot as a Render web service."""
import os
from aiohttp import web


def configured_port():
    try:
        port = int(os.getenv('PORT', '10000'))
    except ValueError:
        raise ValueError('PORT must be a numeric TCP port.') from None
    if not 1 <= port <= 65535:
        raise ValueError('PORT must be between 1 and 65535.')
    return port


class HealthServer:
    def __init__(self, is_ready):
        self.is_ready = is_ready
        self.runner = None
        self.port = None

    async def health(self, request):
        ready = bool(self.is_ready())
        status = 503 if request.path == '/ready' and not ready else 200
        return web.json_response({'ok': True, 'discord_ready': ready,
                                  'key_packages': ['tweaks', 'premium'],
                                  'version': 'render-health-v1'}, status=status)

    async def start(self, port=None):
        if self.runner is not None:
            return self.port
        port = configured_port() if port is None else port
        application = web.Application()
        for route in ('/', '/health', '/ready'):
            application.router.add_get(route, self.health)
        runner = web.AppRunner(application, access_log=None, shutdown_timeout=5)
        try:
            await runner.setup()
            await web.TCPSite(runner, host='0.0.0.0', port=port).start()
        except BaseException:
            await runner.cleanup()
            raise
        self.runner = runner
        self.port = runner.addresses[0][1]
        return self.port

    async def close(self):
        if self.runner is not None:
            runner, self.runner = self.runner, None
            self.port = None
            await runner.cleanup()
