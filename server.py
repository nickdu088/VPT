#!/usr/bin/env python
import json
from queue import Queue
from uuid import uuid4
from aiohttp import web
from aiohttp.web import Request, Response
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

class ProxyChannel:
    def __init__(self, host, settings: dict):
        self.host = host
        self.settings = settings
        self.client = None
        self.host_queue = Queue()
        self.client_queue = Queue()

    def SetClient(self, client):
        if self.client is None:
            self.client = client
            return True
        else:
            return False

    def GetMessage(self, addr):
        logg.info(f"Getting message from {addr}")
        if addr == self.host and not self.host_queue.empty():
            return self.host_queue.get()
        elif addr == self.client and not self.client_queue.empty():
            return self.client_queue.get()
        else:
            return None
        
    def AddMessage(self, addr, item):
        logg.info(f"Adding message from {addr}: {item}")
        if self.host == addr and not self.client_queue.full():
            self.client_queue.put(item)
            return True
        elif self.client == addr and not self.host_queue.full():
            self.host_queue.put(item)
            return True
        else:
            return False
    

class ProxyRequestHandler():

    channels = {}
    BUFFER = 1024 * 50 

    def _get_connection_id(self, request: Request):
        return request.url.name

    def _get_channel(self, request: Request):
        """get the socket which connects to the target address for this connection"""
        id = self._get_connection_id(request)
        return self.channels.get(id, None)

    def _get_request_address(self, request: Request):
        return request.remote
        # return request.transport.get_extra_info('peername')

    def _close_channel(self, request: Request):
        """ close the current socket"""
        s = self._get_channel(request)
        if s:
            del s

    def do_GET(self, request: Request):
        """GET: Read data from TargetAddress and return to client through http response"""
        s = self._get_channel(request)
        if s:
            data = s.GetMessage(self._get_request_address(request))
            logg.info('Data received from queue: %s' % data)
            return Response(status=200, body=data if data else b'')
        else:
            logg.error('Connection With ID %s has not been established' % self._get_connection_id(request))
            return Response(status=400)

    async def do_POST(self, request: Request):
        """POST: Create TCP Connection to the TargetAddress"""
        logg.info('Initializing connection')
        data = await request.json()

        if "channel" in data and data["channel"]:
            channel_id = data["channel"]
            if channel_id in self.channels:
                channel = self.channels[channel_id]
                channel.SetClient(self._get_request_address(request))
                return Response(body=json.dumps(channel.settings), status=200)
            else:
                return Response(body="Channel not found", status=404)
        elif "port" in data and data["port"] != -1:
            channel_id = str(uuid4())
            if channel_id not in self.channels:
                data["channel"] = channel_id
                channel = ProxyChannel(self._get_request_address(request), data)
                self.channels[channel_id] = channel
                return Response(body=json.dumps(channel.settings), status=200)
            else:
                return Response(body="Client already exists", status=409)
        else:
            return Response(body="Invalid request", status=400)

    async def do_PUT(self, request: Request):
        """Read data from HTTP Request and send to TargetAddress"""
        s = self._get_channel(request)
        if not s:
            logg.error("Connection with id %s doesn't exist" % id)
            return Response(status=400)
        data = await request.read()
        # save the data in the queue
        logg.info('Saving data .... %s' % data)
        s.AddMessage(self._get_request_address(request), data)
        return Response(status=200)

    def do_DELETE(self, request: Request): 
        id = self._get_connection_id(request) 
        logg.info('Closing connection with ID %s' % id)
        if id is not None:
            del self.channels[id]
        return Response(status=200)
        

app = web.Application()
app.router.add_get('/{id}', lambda request: ProxyRequestHandler().do_GET(request))
app.router.add_post('/', lambda request: ProxyRequestHandler().do_POST(request))
app.router.add_put('/{id}', lambda request: ProxyRequestHandler().do_PUT(request))
app.router.add_delete('/{id}', lambda request: ProxyRequestHandler().do_DELETE(request))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Tunnel Server")
    parser.add_argument("-p", default=9999, dest='port', help='Specify port number server will listen to', type=int)
    args = parser.parse_args()
    logg.info("Starting server on port %s" % args.port)
    web.run_app(app, host='0.0.0.0', port=args.port)
