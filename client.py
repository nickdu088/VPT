#!/usr/bin/env python
import json
import socket
import socketserver
import time
import requests
from uuid import uuid4
import threading
import argparse
import logging
import base64
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

BUFFER = 1024 * 50
TUNNEL_URL = "http://192.168.0.67:9999"

class TunnelPersistentConnection:
  
    def __init__(self, connection_id : str = None, port : int = -1):
        self.id = connection_id
        self.port = port
        self.session = requests.Session()
        self.session.verify = True
        self.sender = None
        self.lock = threading.Lock()

    def get_settings(self):
        return json.dumps({"channel": self.id, "port": self.port})

    def get_channel_url(self):
        if self.id:
            return TUNNEL_URL + "/" + self.id
        else:
            return TUNNEL_URL

    def create(self):
        logg.info("Creating connection to remote tunnel")
        headers = {"Content-Type": "application/json", "Accept": "text/plain"}
        try:
            data = self.get_settings()
            logg.info("Creating connection with settings: %s" % data)
            response = self.session.post(url=TUNNEL_URL, data=self.get_settings(), headers=headers)
            if response.status_code == 200:
                settins = response.json()
                self.id = settins["channel"]
                self.port = int(settins["port"])
                logg.info('Successfully create connection : %s' % self.get_settings())
                return True
            logg.info('Fail to establish connection: status %s because %s' % (response.status_code, response.reason))
            return False 
        except Exception as ex:
            logg.error("Error Creating Connection: %s" % ex)
            return False

    def forward(self, data, id):
        with self.lock:
            headers = {"Content-Type": "application/json", "Accept": "text/plain"}
            if data:
                data_tosent = {"id": id, "data": base64.b64encode(data).decode()}
            else:
                data_tosent = {"id": id}
            response = self.session.put(url= self.get_channel_url(), data=json.dumps(data_tosent), headers=headers)
            if (response.status_code == 200):
                logg.info("Data forwarded to remote tunnel")
                return True
            else:
                logg.info("Fail to forward data to remote tunnel error: %s" % response.reason)
                return False

    def receive(self) -> Tuple[str, bytes]:
        with self.lock:
            response = self.session.get(self.get_channel_url())
            if response.status_code == 200 and response.content != b'':
                data_received = response.json()
                logg.info("Data received from remote tunnel")
                if "id" in data_received and "data" in data_received:
                    return data_received["id"], base64.b64decode(data_received["data"])
                elif "id" in data_received:
                    return data_received["id"], None
            return None, None

    def close(self):
        logg.info("Close connection to target at remote tunnel")
        self.session.delete(self.get_channel_url())
        self.session.close()

    def run(self, remote_addr):
        senders = {}
        while True:
            try:
                id, data = self.receive()
                if id and not data:
                    if id not in senders:
                        logg.info("Creating sender")
                        sender = TCPProxyClient(remote_addr, id, self)
                        sender.start()
                        senders[id] = sender
                    else:
                        logg.info("Sender already exist")
                        senders.get(id).stop()
                        senders.get(id).join()
                        del senders[id]
                if id and data:
                    logg.info("Data received from tunnel: %s" % data)
                    if id not in senders:
                        logg.error("Sender not found")
                    senders.get(id).send(data)
                else:
                    time.sleep(1)
            except Exception as ex:
                logg.error("Error Receiving Data: %s" % ex)
                break

class ReceiveThread(threading.Thread):

    """
    Thread to receive data from remote host
    """

    def __init__(self, connection, client):
        threading.Thread.__init__(self, name="Receive-Thread")
        self.client = client
        self.conn = connection
        self.id = id
        self._stop = threading.Event()

    def run(self):
        while not self.stopped():
            try:
                logg.info("Retreiving data from remote tunneld")
                id, data = self.conn.receive()
                if data:
                    logg.info("Data received ... %s" % data)
                    self.client.send(id, data)
                else:
                    # logg.info("No data received")
                    # sleep for sometime before trying to get data again
                    time.sleep(1)
            except Exception as ex:
                logg.error("Error: %s" % ex)
                break

    def stop(self):
        self._stop.set()

    def stopped(self):
        return self._stop.is_set()

class TCPProxyHandler(socketserver.BaseRequestHandler):

    def handle(self):
        # self.rfile is a file-like object created by the handler.
        # We can now use e.g. readline() instead of raw recv() calls.
        # We limit ourselves to 10000 bytes to avoid abuse by the sender.
        while True:
            try:
                data = self.request.recv(BUFFER)
                logg.info("Getting data from client to send")
                if data == b'':
                    logg.info("Client's socket connection broken")
                    break
                logg.info("Sending data ... %s " % data)
                self.server.forward_request(data, str(self.request.__hash__()))
            except Exception as ex:
                logg.error("Error: %s" % ex)
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
        # new connection to remote server
        self.tunnelConnection.forward(None, id)
        return super().process_request(request, client_address)

    def send(self, id, data):
        if id in self.sockets:
            self.sockets[id].sendall(data)

    def forward_request(self, data, id):
        self.tunnelConnection.forward(data, id)

    def shutdown_request(self, request):
        id = str(request.__hash__())
        del self.sockets[id]
        # close connection to remote server
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
        threading.Thread.__init__(self, name="Client-Thread")
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection = connection
        self.id = id
        # open socket connection to remote server
        self.s.connect_ex((remote_addr['host'], int(remote_addr['port'])))
        # use non-blocking socket
        # self.s.setblocking(0)
        self._stop = threading.Event()
    
    def send(self, data):
        self.s.sendall(data)

    def run(self):
        try:
            while not self.stopped():
                data = self.s.recv(BUFFER)  
                if data:
                    logg.info("Data received from tunnel ... %s" % data)
                    self.connection.forward(data, self.id)
                else:
                    logg.info("No data received")
                    # sleep for sometime before trying to get data again
                    time.sleep(1)
        except Exception as ex:
            logg.error("Error: %s" % ex)
        finally: 
            self.s.close()
            self.connection.forward(None, self.id)

    def stop(self):
        self._stop.set()
        self.s.close()

    def stopped(self):
        return self._stop.is_set()

    def close(self):
        self.s.close()

if __name__ == "__main__":
    """Parse argument from command line and start tunnel"""

    parser = argparse.ArgumentParser(description='Start Tunnel Client')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-r', dest='remote', help='Specify the host and port of the remote server to tunnel to (e.g. localhost:22)')
    group.add_argument('-c', dest='channel', help='Specify the channel Id')

    args = parser.parse_args()

    if args.channel:
        tunnelConnection = TunnelPersistentConnection(connection_id = args.channel)
        if tunnelConnection.create():
            logg.info("Connection established")
            with TCPProxyServer(('', tunnelConnection.port), TCPProxyHandler, tunnelConnection) as server:
                logg.info(f"Waiting for connection on port {tunnelConnection.port}...")
                server.serve_forever()
            tunnelConnection.close()
    elif args.remote:
        remote_addr = {"host": args.remote.split(":")[0], "port": args.remote.split(":")[1]}
        tunnelConnection = TunnelPersistentConnection(port = remote_addr['port'])
        if tunnelConnection.create():
            tunnelConnection.run(remote_addr)
            tunnelConnection.close()
            
