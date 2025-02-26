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

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

BUFFER = 1024 * 50

class TunnelPersistentConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
    
    def __init__(self, connection_id = None, port : int = -1):
        self.id = connection_id
        self.port = port
        self.session = requests.Session()
        self.sender = None

    def get_settings(self):
        return json.dumps({"channel": self.id, "port": self.port})

    def get_channel_url(self):
        if self.id:
            return self.get_url() + "/" + self.id
        else:
            return self.get_url()
    
    def get_url(self):
        return "http://192.168.0.1"

    def create(self):
        logg.info("Creating connection to remote tunnel")
        headers = {"Content-Type": "application/json", "Accept": "text/plain"}
        try:
            data = self.get_settings()
            logg.info("Creating connection with settings: %s" % data)
            response = self.session.post(url=self.get_url(), data=self.get_settings(), headers=headers)
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

    def forward(self, data):
        headers = {"Content-Type": "application/text"}
        response = self.session.put(url= self.get_channel_url(), data=base64.b64encode(data), headers=headers)
        if (response.status_code == 200):
            logg.info("Data forwarded to remote tunnel")
            return True
        else:
            logg.info("Fail to forward data to remote tunnel error: %s" % response.reason)
            return False


    def receive(self):
        response = self.session.get(self.get_channel_url())
        data = response.content
        if response.status_code == 200 and data:
            return base64.b64decode(data)
        else: 
            return None

    def close(self):
        logg.info("Close connection to target at remote tunnel")
        self.session.delete(self.get_channel_url())
        self.session.close()

    def run(self):
        sender = None
        while True:
            try:
                data = self.receive()
                if data:
                    logg.info("Data received from tunnel: %s" % data)
                    if sender == None:
                        logg.info("Creating sender")
                        sender = TCPProxyClient("localhost", self.port, self)
                        sender.start()
                    sender.send(data)
                else:
                    time.sleep(1)
            except Exception as ex:
                logg.error("Error Receiving Data: %s" % ex)
                break

class ReceiveThread(threading.Thread):

    """
    Thread to receive data from remote host
    """

    def __init__(self, client, connection):
        threading.Thread.__init__(self, name="Receive-Thread")
        self.client = client
        self.conn = connection
        self._stop = threading.Event()

    def run(self):
        while not self.stopped():
            try:
                logg.info("Retreiving data from remote tunneld")
                data = self.conn.receive()
                if data:
                    logg.info("Data received ... %s" % data)
                    self.client.sendall(data)
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
                self.server.forward_request(data)
            except socket.timeout:
                logg.info("time out")
            except Exception as ex:
                logg.error("Error: %s" % ex)
                break

class TCPProxyServer(socketserver.TCPServer):
    def __init__(self, server_address, RequestHandlerClass, connection, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.connection = connection

    def process_request(self, request, client_address):
        self.receiver = ReceiveThread(request, self.connection)
        self.receiver.start()
        return super().process_request(request, client_address)
        

    def forward_request(self, data):
        self.connection.forward(data)

    def shutdown_request(self, request):
        self.connection.close()
        if self.receiver.is_alive():
            self.receiver.stop()
            # self.receiver.join()
        return super().shutdown_request(request)

class TCPProxyClient(threading.Thread):
    def __init__(self, host, port, connection):
        threading.Thread.__init__(self, name="Client-Thread")
        self.host = host
        self.port = port
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection = connection
        # open socket connection to remote server
        self.s.connect_ex((self.host, self.port))
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
                    self.connection.forward(data)
                else:
                    logg.info("No data received")
                    # sleep for sometime before trying to get data again
                    time.sleep(1)
        except Exception as ex:
            logg.error("Error: %s" % ex)
        finally: 
            self.s.close()

    def stop(self):
        self._stop.set()
        self.s.close()

    def stopped(self):
        return self._stop.is_set()

    def close(self):
        self.s.close()

if __name__ == "__main__":
    """Parse argument from command line and start tunnel"""

    parser = argparse.ArgumentParser(description='Start Tunnel')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-p', dest='port', help='Port the tunnel connect to')
    group.add_argument('-c', dest='channel', help='Specify the channel Id')

    args = parser.parse_args()

    if args.channel:
        with TunnelPersistentConnection(connection_id = args.channel) as persistentConnection:
            if persistentConnection.create():
                logg.info("Connection established")
                with TCPProxyServer(('', persistentConnection.port), TCPProxyHandler, persistentConnection) as server:
                    logg.info("Waiting for connection...")
                    server.serve_forever()
    elif args.port:
        with TunnelPersistentConnection(port = args.port) as persistentConnection:
            if persistentConnection.create():
                persistentConnection.run()
            
