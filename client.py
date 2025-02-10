import socket
import sys
import json
import requests

def createHost(url: str, type: str, port: int):
    try:
        if type == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        elif type == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            print(f"Unsupported socket type: {type}")
            sys.exit(1)
        sock.connect(("192.168.0.110", port))

        print(f"Connected to localhost on port {port} with type {type}")

        while True:
            try:
                data = sock.recv(1024)
                if not data:
                    response = requests.get(url)
                    socket.sendall(response.content)
                print(f"Received data: {data.decode('utf-8')}")
                requests.post(url, data)
            except Exception as e:
                print(f"Error receiving data: {e}")
                break

        sock.close()
    except Exception as e:
        print(f"Failed to connect to localhost on port {port}: {e}")
    else:
        print("Type and port parameters are required to create a socket connection.")

def createClient(url: str, type: str, port: int):
    try:
        if type == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            print(f"TCP server listening on port {port}")
            conn, addr = sock.accept()
            print(f"Connection from {addr}")
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                print(f"Received data: {data.decode('utf-8')}")
                response = requests.get(url)
                conn.sendall(response.content)
            conn.close()
        elif type == "udp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("127.0.0.1", port))
            print(f"UDP server listening on port {port}")
            while True:
                data, addr = sock.recvfrom(1024)
                if not data:
                    break
                print(f"Received data from {addr}: {data.decode('utf-8')}")
                response = requests.get(url)
                sock.sendto(response.content, addr)
        else:
            print(f"Unsupported socket type: {type}")
            sys.exit(1)
    except Exception as e:
        print(f"Failed to create server on port {port}: {e}")
    finally:
        sock.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python test.py -t <type> | -c <channel> | -p <port>")
        sys.exit(1)
    
    parameters = sys.argv

    for i in range(1, len(parameters)):
        parameter = parameters[i]
        if parameter == "-t":
            if i + 1 >= len(parameters):
                print("Usage: python test.py -t <type>")
                sys.exit(1)
            type_param = parameters[i + 1]
            print(f"Type parameter received: {type_param}")
        elif parameter == "-c":
            if i + 1 >= len(parameters):
                print("Usage: python test.py -c <channel>")
                sys.exit(1)
            channel_param = parameters[i + 1]
            print(f"Channel parameter received: {channel_param}")
        elif parameter == "-p":
            if i + 1 >= len(parameters):
                print("Usage: python test.py -p <port>")
                sys.exit(1)
            port_param = parameters[i + 1]
            print(f"Port parameter received: {port_param}")

    params_dict = {}
    for i in range(1, len(parameters)):
        parameter = parameters[i]
        if parameter == "-t" and i + 1 < len(parameters):
            params_dict["type"] = parameters[i + 1]
        elif parameter == "-c" and i + 1 < len(parameters):
            params_dict["channel"] = parameters[i + 1]
        elif parameter == "-p" and i + 1 < len(parameters):
            params_dict["port"] = parameters[i + 1]

    url = "http://192.168.0.60:8080"
    response = requests.put(url, json=params_dict)

    if response.status_code > 299:
        print(f"Error from server {response.content}")
        sys.exit(1)

    data = response.json()
    if "channel" in data:
        url += f"/{data['channel']}"
        createHost(url, params_dict['type'].lower(), int(params_dict['port']))
    elif "type" in data and "port" in data:
        url += f"/{params_dict['channel']}"
        createClient(url, data['type'], int(data['port']))


if __name__ == "__main__":
    main()
