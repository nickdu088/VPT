# from js import Response
import json
from urllib.parse import urlparse, parse_qs
from aiohttp import web
from aiohttp.web import Request, Response
from queue import Queue

# Initialize an in-memory key-value store
channel_store = {}

class RelayAgent:
    def __init__(self, host: str, settings: dict):
        self.host = host
        self.settings = settings
        self.client = None
        self.host_queue = Queue()
        self.client_queue = Queue()

    def AddClient(self, client: str):
        if self.client is None:
            self.client = client
            return True
        else:
            return False

    def GetMessage(self, ip: str):
        if ip == self.host and not self.host_queue.empty():
            return self.host_queue.get()
        elif ip == self.client and not self.client_queue.empty():
            return self.client_queue.get()
        else:
            return None
        
    def AddMessage(self, ip: str, item):
        print(f"Adding message from {ip}: {item}")
        if ip == self.host:
            self.client_queue.put(item)
            return True
        elif ip == self.client:
            self.host_queue.put(item)
            return True
        else:
            return False

# Define a function that will create a new resource
async def CreateRlay(request: Request) -> Response:
    data = await request.json()
    host_ip = request.remote

    if "channel" in data:
        channel_id = data["channel"]
        if channel_id in channel_store:
            channel = channel_store[channel_id]
            channel.AddClient(host_ip)
            return Response(body=json.dumps(channel.settings), status=201)
        else:
            return Response(body="Channel not found", status=404)
    elif "type" in data and "port" in data:
        channel_id = "12345" # generate a unique channel id
        if channel_id not in channel_store:
            channel_store[channel_id] = RelayAgent(host_ip, data)
            channel = {"channel": channel_id}
            return Response(body=json.dumps(channel), status=201)
        else:
            return Response(body="Client already exists", status=409)
    else:
        return Response(body="Invalid request", status=400)
    # # Save the key_value_map to a database or file (this part is not implemented)
    # # For demonstration purposes, we will print the key_value_map
    # for k, v in channel_store.items():
    #     print (f"Channel: {v} , host: {v.host} <-> clinet: {v.client}")

# Define a function that will relay the request to the appropriate resource based on the key
async def AddRelayMessage(request: Request) -> Response:
    channel = request.url.name
    if channel in channel_store:
        data = await request.read()
        channel_store[channel].AddMessage(request.remote, data)
        # Forward the request to the client_ip
        # (this part is not implemented, but you can use aiohttp.ClientSession to send a request to the client_ip)
        return Response(body="Request forwarded to client", status=200)
    else:
        return Response(body="Key not found", status=404)

# Define a function that will fetch the value of a resource based on the key
async def GetRelayMessage(request: Request) -> Response:
    channel_id = request.url.name
    if channel_id in channel_store:
        channel = channel_store[channel_id]
        # Fetch the value from the client_ip
        # (this part is not implemented, but you can use aiohttp.ClientSession to send a request to the client_ip)
        msg = channel.GetMessage(request.remote)
        return Response(body=msg, status=200)
    else:
        return Response(body="Key not found", status=404)
    
async def on_fetch(request: Request) -> Response:
    if request.method == "GET":
        return await GetRelayMessage(request)
    elif request.method == "POST": # connect to existing resource
        return await AddRelayMessage(request)
    elif request.method == "PUT": # create new resource
        return await CreateRlay(request)
    elif request.method == "DELETE":
        return Response(body="Hello world!")
    else:
        return Response(body="Access Denied", status=403)
    # Parse the incoming request URL
    url = request.url #urlparse(request.url)
    # Parse the query parameters into a Python dictionary
    params = url.query #parse_qs(url.query)

    if "name" in params:
        greeting = "Hello there, {name}".format(name=params["name"])
        return Response(body=greeting)

    if url.path == "/favicon.ico":
      return Response.new("")

    return Response(body="Hello world!")

app = web.Application()
app.router.add_get('/{channel}', on_fetch)
app.router.add_post('/{channel}', on_fetch)
app.router.add_put('/', on_fetch)
app.router.add_delete('/', on_fetch)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=8080)