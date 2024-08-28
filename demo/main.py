#!/usr/bin/env python

import socket
import sys
import threading
import time
import traceback
import select

import paramiko
import paramiko.util

# setup logging
paramiko.util.log_to_file("demo_server.log")

host_key = paramiko.RSAKey(filename="./test_rsa.key")

request = {}


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        request["kind"] = kind
        request["chanid"] = chanid
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if username == "guang":
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_gssapi_keyex(
            self, username, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None
    ):
        return paramiko.AUTH_FAILED

    def check_channel_x11_request(
        self, channel, single_connection, auth_protocol, auth_cookie, screen_number
    ):
        request["x11"] = True
        request["x11_chan"] = channel
        request["x11_args"] = {
            "single_connection": single_connection,
            "auth_protocol": auth_protocol,
            "auth_cookie": auth_cookie,
            "screen_number": screen_number,
        }
        return True

    def enable_auth_gssapi(self):
        return True

    def get_allowed_auths(self, username):
        return "publickey,password"

    def check_channel_shell_request(self, channel):
        self.event.set()
        request["shell"] = True
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        request['pty'] = True
        request['pty_args'] = {
            'term': term, 'width': width, 'height': height,
        }
        return True


remote_ssh = paramiko.SSHClient()
remote_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
remote_ssh.connect("foo", username="root")


def bridge(client_chan):
    transport = remote_ssh.get_transport()
    remote_chan = transport.open_session()

    def x11_handler(x11_chan, src_addr_and_port):
        def handle_it():
            try:
                client_x11 = client_chan.transport.open_x11_channel(src_addr_and_port)
            except Exception as e:
                print("Error >>> : ", e)
                return

            while True:
                r1, _, __ = select.select([x11_chan, client_x11], [], [])

                if x11_chan in r1:
                    print("Rev from x1: ")
                    data = x11_chan.recv(1024)
                    if len(data) == 0:
                        break
                    client_x11.send(data)

                if client_x11 in r1:
                    print("Rev from client: ")
                    data = client_x11.recv(1024)
                    if len(data) == 0:
                        break
                    x11_chan.send(data)

        threading.Thread(target=handle_it).start()

    if request.get('x11'):
        x11_args = request.get('x11_args')
        x11_args['handler'] = x11_handler
        remote_chan.request_x11(**x11_args)

    if request.get('pty'):
        remote_chan.get_pty()

    if request.get("shell"):
        remote_chan.invoke_shell()

    while True:
        r, _, __ = select.select([client_chan, remote_chan], [], [])
        if client_chan in r:
            data = client_chan.recv(1024)
            if len(data) == 0:
                break
            remote_chan.send(data)

        if remote_chan in r:
            data = remote_chan.recv(1024)
            if len(data) == 0:
                break
            client_chan.send(data)


def handle_client(client):
    try:
        t = paramiko.Transport(client)
        t.add_server_key(host_key)
        server = Server()
        try:
            t.start_server(server=server)
        except paramiko.SSHException:
            print("*** SSH negotiation failed.")
            sys.exit(1)

        # wait for auth
        chan = t.accept(20)
        if chan is None:
            print("*** No channel.")
            return

        server.event.wait(10)
        if not server.event.is_set():
            print("*** Client never asked for a shell.")
            return

        bridge(chan)
        chan.close()

    except Exception as e:
        print("*** Caught exception: " + str(e.__class__) + ": " + str(e))
        traceback.print_exc()
        try:
            t.close()
        except:
            pass
        sys.exit(1)


def main():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 2200))
        print("Listening at :2200")
    except Exception as e:
        print("*** Bind failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)

    try:
        sock.listen(100)
        while True:
            client, addr = sock.accept()
            print("Got a connection from: %s:%s" % (addr[0], addr[1]))
            t = threading.Thread(target=handle_client, args=(client,))
            t.daemon = True
            t.start()

    except Exception as e:
        print("*** Listen/accept failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
