import socket
import sys
import json
import requests

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

    if response.status_code == 200:
        print("Data successfully sent to the server.")
    else:
        print(f"Failed to send data to the server. Status code: {response.content}")

    url += "/12345"

    if "type" in params_dict and "port" in params_dict:
        try:
            if params_dict["type"].lower() == "tcp":
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            elif params_dict["type"].lower() == "udp":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            else:
                print(f"Unsupported socket type: {params_dict['type']}")
                sys.exit(1)
            sock.connect(("192.168.0.110", int(params_dict["port"])))

            print(f"Connected to localhost on port {params_dict['port']} with type {params_dict['type']}")

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
            print(f"Failed to connect to localhost on port {params_dict['port']}: {e}")
    else:
        print("Type and port parameters are required to create a socket connection.")

if __name__ == "__main__":
    main()
