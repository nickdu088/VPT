#!/usr/bin/env python
import json
import socket
import socketserver
import time
import http.client
import threading
import argparse
import logging
import base64
import lzma
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

BUFFER = 1024 * 128  # 128KB size buffer
TUNNEL_URL = "192.168.0.67:9999"

class TunnelConnection:
    def __init__(self, connection_id: str = None, port: int = -1):
        self.id = connection_id
        self.port = port
        self.conn = None
        self.lock = threading.Lock()

    def get_settings(self):
        return json.dumps({"channel": self.id, "port": self.port})

    def get_channel_url(self):
        return f"/{self.id}" if self.id else "/"

    def connect_server(self):
        self.conn = http.client.HTTPConnection(TUNNEL_URL)

    def create(self):
        logg.info("Creating connection to remote tunnel")
        try:
            self.connect_server()
            data = self.get_settings()
            headers = {"Content-Type": "application/json", "Accept": "text/plain"}
            self.conn.request("POST", "/", body=data, headers=headers)
            response = self.conn.getresponse()
            if response.status == 200:
                settings = json.loads(response.read())
                self.id = settings["channel"]
                self.port = int(settings["port"])
                logg.info('Successfully created connection: %s', self.get_settings())
                return True
            logg.warning('Failed to establish connection: status %s because %s', response.status, response.reason)
            return False
        except Exception as ex:
            logg.error("Error Creating Connection: %s", ex)
            return False

    def forward(self, data, id):
        headers = {"Content-Type": "application/json", "Accept": "text/plain"}
        if data:
            data = lzma.compress(data)
            data_to_send = {"id": id, "data": base64.b64encode(data).decode()}
        else:
            data_to_send = {"id": id}
        for attempt in range(3):
            try:
                with self.lock:
                    self.conn.request("PUT", self.get_channel_url(), body=json.dumps(data_to_send), headers=headers)
                response = self.conn.getresponse()
                response.read()  # Clear the response
                if response.status == 200:
                    logg.info("Data forwarded to remote tunnel")
                    return True
                else:
                    logg.warning("Attempt %d: Failed to forward data to remote tunnel: %s", attempt + 1, response.reason)
                    return False
            except Exception as ex:
                logg.error("Attempt %d: Error forwarding data: %s", attempt + 1, ex)
                time.sleep(1)  # Wait before retrying

    def receive(self) -> Tuple[str, bytes]:
        for attempt in range(3):
            try:
                with self.lock:
                    self.conn.request("GET", self.get_channel_url())
                    response = self.conn.getresponse()
                    if response.status == 200:
                        data_received = response.read()
                        if data_received:
                            data_received = json.loads(data_received)
                            logg.info("Data received from remote tunnel")
                            if "id" in data_received and "data" in data_received:
                                compressed_data = base64.b64decode(data_received["data"])
                                return data_received["id"], lzma.decompress(compressed_data)
                            elif "id" in data_received:
                                return data_received["id"], None
                return None, None
            except Exception as ex:
                logg.error("Attempt %d: Error receiving data: %s", attempt + 1, ex)
                time.sleep(1)  # Wait before retrying
        return None, None

    def close(self):
        logg.info("Closing connection to target at remote tunnel")
        self.conn.request("DELETE", self.get_channel_url())
        self.conn.getresponse()  # Clear the response
        self.conn.close()
        self.conn = None

    def run(self, remote_addr):
        senders = {}
        while True:
            try:
                id, data = self.receive()
                if id and not data:
                    if id not in senders:
                        logg.info("Creating sender %s", id)
                        sender = TCPProxyClient(remote_addr, id, self)
                        sender.start()
                        senders[id] = sender
                    else:
                        logg.info("Closing sender %s", id)
                        senders[id].stop()
                        #senders[id].join()
                        del senders[id]
                if id and data and id in senders:
                    senders[id].send(data)
                else:
                    time.sleep(1)
            except Exception as ex:
                logg.error("Error Receiving Data: %s", ex)
                break

class ReceiveThread(threading.Thread):

    def __init__(self, connection, client):
        super().__init__(name="Receive-Thread")
        self.client = client
        self.conn = connection
        self._stop = threading.Event()

    def run(self):
        while not self.stopped():
            try:
                logg.info("Retrieving data from remote tunnel")
                id, data = self.conn.receive()
                if data:
                    self.client.send(id, data)
                else:
                    time.sleep(1)
            except Exception as ex:
                logg.error("Error: %s", ex)
                break

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.is_set()

class TCPProxyHandler(socketserver.BaseRequestHandler):

    def handle(self):
        while True:
            try:
                data = self.request.recv(BUFFER)
                if not data:
                    logg.info("Client's socket connection broken")
                    break
                self.server.forward_request(data, str(self.request.__hash__()))
            except Exception as ex:
                logg.error("Error: %s", ex)
                break

class TCPProxyServer(socketserver.ThreadingTCPServer):
    def __init__(self, server_address, RequestHandlerClass, tunnelConnection, bind_and_activate=True):
        self.tunnelConnection = tunnelConnection
        self.sockets = {}
        self.receiver = None
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def process_request(self, request, client_address):
        id = str(request.__hash__())
        self.sockets[id] = request
        self.tunnelConnection.forward(None, id)
        return super().process_request(request, client_address)

    def send(self, id, data):
        if id in self.sockets:
            self.sockets[id].sendall(data)

    def forward_request(self, data, id):
        return self.tunnelConnection.forward(data, id)

    def shutdown_request(self, request):
        id = str(request.__hash__())
        del self.sockets[id]
        self.tunnelConnection.forward(None, id)
        return super().shutdown_request(request)

    def server_activate(self):
        if self.receiver is None:
            self.receiver = ReceiveThread(self.tunnelConnection, self)
            self.receiver.start()
        super().server_activate()

    def server_close(self):
        if self.receiver.is_alive():
            self.receiver.stop()
        super().server_close()

class TCPProxyClient(threading.Thread):
    def __init__(self, remote_addr, id, connection):
        super().__init__(name="Client-Thread")
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection = connection
        self.id = id
        self.s.connect_ex((remote_addr['host'], int(remote_addr['port'])))
        self._stop = threading.Event()

    def send(self, data):
        self.s.sendall(data)

    def run(self):
        try:
            while not self.stopped():
                data = self.s.recv(BUFFER)
                if data:
                    self.connection.forward(data, self.id)
                else:
                    time.sleep(1)
        except Exception as ex:
            logg.error("Error: %s", ex)
        finally: 
            self.s.close()
            self.connection.forward(None, self.id)

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.is_set()

    def close(self):
        self.s.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start Tunnel Client')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', dest='remote', help='Specify the host and port of the remote server to tunnel to (e.g. localhost:22)')
    group.add_argument('-c', dest='channel', help='Specify the channel Id')

    args = parser.parse_args()

    if args.channel:
        tunnelConnection = TunnelConnection(connection_id=args.channel)
        if tunnelConnection.create():
            logg.info("Connection established")
            with TCPProxyServer(('', tunnelConnection.port), TCPProxyHandler, tunnelConnection) as server:
                logg.info(f"Waiting for connection on port {tunnelConnection.port}...")
                server.serve_forever()
    elif args.remote:
        remote_addr = {"host": args.remote.split(":")[0], "port": args.remote.split(":")[1]}
        tunnelConnection = TunnelConnection(port=remote_addr['port'])
        if tunnelConnection.create():
            tunnelConnection.run(remote_addr)
            tunnelConnection.close()
