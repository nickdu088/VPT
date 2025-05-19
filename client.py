#!/usr/bin/env python
import asyncio
import aiohttp
import argparse
import logging
import base64
import lzma
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

BUFFER = 1024 * 128  # 128KB size buffer
TUNNEL_URL = "http://192.168.0.67:9999"

class TunnelConnection:

    def __init__(self, connection_id: str = None, port: int = -1):
        self.id = connection_id
        self.port = port
        self.session = aiohttp.ClientSession()

    def get_settings(self):
        return {"channel": self.id, "port": self.port}

    def get_channel_url(self):
        return f"{TUNNEL_URL}/{self.id if self.id else ''}"

    async def create(self):
        logg.info("Creating connection to remote tunnel")
        try:
            async with self.session.post(url=TUNNEL_URL, json=self.get_settings()) as response:
                if response.status == 200:
                    settings = await response.json()
                    self.id = settings["channel"]
                    self.port = int(settings["port"])
                    logg.info('Successfully created connection: %s', self.get_settings())
                    return True
                logg.warning('Failed to establish connection: status %s because %s', response.status, response.reason)
                if self.session:
                    await self.session.close()
        except Exception as ex:
            logg.error("Error Creating Connection: %s", ex)
        return False

    async def forward(self, data, id):
        data_to_send = {"id": id, "data": base64.b64encode(lzma.compress(data)).decode()} if data else {"id": id}
        async with self.session.put(url=self.get_channel_url(), json=data_to_send) as response:
            if response.status == 200:
                logg.info("Data >> to remote tunnel")
                return True
            else:
                logg.warning("Failed to forward data to remote tunnel: %s", response.reason)
                return False

    async def receive(self) -> Tuple[str, bytes]:
        async with self.session.get(self.get_channel_url()) as response:
            if response.status == 200 and response.content_length not in (None, 0):
                logg.info("Data << from remote tunnel")
                data_received = await response.json()
                if "id" in data_received and "data" in data_received:
                    compressed_data = base64.b64decode(data_received["data"])
                    return data_received["id"], lzma.decompress(compressed_data)
                elif "id" in data_received:
                    return data_received["id"], None
            return None, None

    async def close(self):
        logg.info("Closing connection to target at remote tunnel")
        async with self.session.delete(self.get_channel_url()) as response:
            if response.status == 200:
                await self.session.close()
                logg.info("Successfully closed connection")
            else:
                logg.warning("Failed to close connection: %s", response.reason)

    async def run(self, remote_addr):
        senders = {}
        while True:
            try:
                id, data = await self.receive()
                if id and not data:
                    if id not in senders:
                        logg.info("Creating sender %s", id)
                        sender = TCPProxyClient(remote_addr, id, self)
                        await sender.connect()
                        task = asyncio.create_task(sender.run())
                        senders[id] = (sender, task)
                    else:
                        logg.info("Closing sender %s", id)
                        senders[id][1].cancel()
                        del senders[id]
                if id and data and id in senders:
                    await senders[id][0].send(data)
                else:
                    await asyncio.sleep(1)
            except Exception as ex:
                logg.error("Error Receiving Data: %s", ex)
                break

class TCPProxyServer:
    def __init__(self, port, connection):
        self.reader = None
        self.writer = None
        self.connection = connection
        self.port = port
        self.senders = {}
        self.receiver = None

    async def receive(self):
        while True:
            try:
                id, data = await self.connection.receive()
                if data:
                    await self.send(id, data)
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logg.error("Error in receive: %s", e)

    async def start(self):
        self.receiver = asyncio.create_task(self.receive())
        async with await asyncio.start_server(self.handle_client, port=self.port) as server:
            await server.serve_forever()
            self.receiver.cancel()
            await self.receiver

    async def handle_client(self, reader, writer):
        id = str(writer.__hash__())
        logg.info("New client connected: %s", id)
        sender = asyncio.create_task(self.handle_connection(reader, writer))
        self.senders[id] = (writer, sender)
    
    async def handle_connection(self, reader, writer):
        id = str(writer.__hash__())
        await self.connection.forward(None, id)
        try:
            while True:
                data = await reader.read(BUFFER)
                if not data:
                    logg.info("Client's socket connection broken")
                    break
                await self.connection.forward(data, id)
        except Exception as e:
            logg.error("Error: %s", e)
        except asyncio.CancelledError:
            pass
        finally:
            await self.connection.forward(None, id)
    
    async def send(self, id, data):
        if id in self.senders:
            self.senders[id][0].write(data)
            await self.senders[id][0].drain()

class TCPProxyClient:
    def __init__(self, remote_addr, id, connection):
        self.reader = None
        self.writer = None
        self.connection = connection
        self.id = id
        self.remote_addr = remote_addr

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.remote_addr['host'], int(self.remote_addr['port'])
            )
        except Exception as ex:
            logg.error("Error connecting to remote server: %s", ex)
            raise

    async def send(self, data):
        if self.writer:
            self.writer.write(data)
            await self.writer.drain()

    async def run(self):
        try:
            while True:
                data = await self.reader.read(BUFFER)
                if not data:
                    logg.info("Connection closed by remote server")
                    break
                await self.connection.forward(data, self.id)
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            logg.error("Error: %s", ex)
        finally:
            await self.connection.forward(None, self.id)
            self.writer.close()
            await self.writer.wait_closed()

async def main():
    parser = argparse.ArgumentParser(description='Start Tunnel Client')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', dest='remote', help='Specify the host and port of the remote server to tunnel to (e.g. localhost:22)')
    group.add_argument('-c', dest='channel', help='Specify the channel Id')

    args = parser.parse_args()

    if args.channel:
        tunnelConnection = TunnelConnection(connection_id=args.channel)
        if await tunnelConnection.create():
            server = TCPProxyServer(tunnelConnection.port, tunnelConnection)
            logg.info(f"Waiting for connection on port {tunnelConnection.port}...")
            await server.start()
    elif args.remote:
        remote_addr = {"host": args.remote.split(":")[0], "port": args.remote.split(":")[1]}
        tunnelConnection = TunnelConnection(port=remote_addr['port'])
        if await tunnelConnection.create():
            await tunnelConnection.run(remote_addr)

if __name__ == "__main__":
    asyncio.run(main())
