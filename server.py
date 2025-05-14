import argparse
import uuid
from aiohttp import web
import asyncio
from asyncio import Queue
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

class TunnelInfoStorage:
    def set_tunnel_info(self, channel_id, channel):
        raise NotImplementedError

    def get_tunnel_info(self, channel_id):
        raise NotImplementedError

    def delete_tunnel_info(self, channel_id):
        raise NotImplementedError
    
class SessionTunnelInfoStorage(TunnelInfoStorage):
    def __init__(self):
        self.storage = {}

    def set_tunnel_info(self, channel_id, channel):
        self.storage[channel_id] = channel

    def get_tunnel_info(self, channel_id):
        return self.storage.get(channel_id)

    def delete_tunnel_info(self, channel_id):
        if channel_id in self.storage:
            del self.storage[channel_id]

tunnel_storage = SessionTunnelInfoStorage()

class ProxyTunnel:
    def __init__(self, host, settings):
        self.host = host
        self.settings = settings
        self.client = None
        self.host_queue = Queue()
        self.client_queue = Queue()

    def get_settings(self):
        return self.settings

    def set_settings(self, settings):
        self.settings = settings

    def set_client(self, client):
        self.client = client
        return True

    async def get_message(self, addr):
        queue = self.host_queue if addr == self.host else self.client_queue
        item = await asyncio.wait_for(queue.get(), timeout=5)
        queue.task_done()
        return item

    async def add_message(self, addr, msg):
        queue = self.client_queue if addr == self.host else self.host_queue
        await queue.put(msg)

async def handle_get(request):
    channel = get_channel(request)
    if channel:
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            },
        )
        await response.prepare(request)

        try:
            while True:
                try:
                    message = await channel.get_message(get_client_ip(request))
                    await response.write(message)
                except ConnectionResetError:
                    break
                except asyncio.TimeoutError:
                    # logg.warning("Timeout waiting for message")
                    if request.transport is None or request.transport.is_closing():
                        break
                    await response.write(b'\n')
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            if request.transport is not None and not request.transport.is_closing():
                await response.write_eof()
        return web.Response(status=200, text="OK")
    return web.Response(status=404, text="Resource not found")

async def handle_post(request):
    data = await request.json()
    if 'channel' in data and data['channel']:
        channel_id = data['channel']
        channel = tunnel_storage.get_tunnel_info(channel_id)
        if channel:
            channel.set_client(get_client_ip(request))
            return web.json_response(channel.get_settings())
    elif 'port' in data and data['port'] != -1:
        channel_id = str(uuid.uuid4())
        settings = {
            'channel': channel_id,
            'port': data['port']
        }
        channel = ProxyTunnel(get_client_ip(request), settings)
        tunnel_storage.set_tunnel_info(channel_id, channel)
        return web.json_response(channel.get_settings())
    return web.Response(status=404, text="Resource not found")

async def handle_put(request):
    channel = get_channel(request)
    if channel:
        await channel.add_message(get_client_ip(request), await request.read())
        return web.Response(status=200)
    return web.Response(status=404, text="Resource not found")

def handle_delete(request):
        channel_id = get_channel_id(request)
        if channel_id:
            tunnel_storage.delete_tunnel_info(channel_id)
        return web.Response(status=200)

def handle_options(request):
    return web.json_response(list(tunnel_storage.storage.keys()))

def get_client_ip(request):
    peername = request.transport.get_extra_info('peername')
    if peername is not None:
        return peername[0]
    return None

def get_channel_id(request):
    channel_id = request.match_info.get('id')
    return channel_id if channel_id else None

def get_channel(request):
    channel_id = get_channel_id(request)
    return tunnel_storage.get_tunnel_info(channel_id)

app = web.Application()
app.router.add_get('/{id}', handle_get)
app.router.add_post('/', handle_post)
app.router.add_put('/{id}', handle_put)
app.router.add_delete('/{id}', handle_delete)
app.router.add_options('/', handle_options)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Tunnel Server")
    parser.add_argument("-p", default=443, dest='port', help='Specify port number server will listen to', type=int)
    args = parser.parse_args()
    logg.info("Starting server on port %s" % args.port)
    web.run_app(app, host='0.0.0.0', port=args.port)
