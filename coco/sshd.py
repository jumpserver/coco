#! coding: utf-8

import os
import logging
import socket
import threading
import paramiko
import sys

from .utils import ssh_key_gen
from .interface import SSHInterface

logger = logging.getLogger(__file__)
BACKLOG = 5


class Request:
    def __init__(self, client, addr):
        self.type = ""
        self.meta = {}
        self.client = client
        self.addr = addr
        self.user = None
        self.change_size_event = threading.Event()
        self.win_size = {}


class SSHServer:
    def __init__(self, app=None):
        self.app = app
        self.stop_event = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.host_key_path = os.path.join(self.app.root_path, 'keys', 'host_rsa_key')
        self.host_key = self.get_host_key()

    def listen(self):
        host = self.app.config["BIND_HOST"]
        port = self.app.config["SSHD_PORT"]
        print('Starting shh server at %(host)s:%(port)s' %
              {"host": host, "port": port})
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(BACKLOG)

    def get_host_key(self):
        if not os.path.isfile(self.host_key_path):
            self.gen_host_key()
        return paramiko.RSAKey(filename=self.host_key_path)

    def gen_host_key(self):
        ssh_key, _ = ssh_key_gen()
        with open(self.host_key_path, 'w') as f:
            f.write(ssh_key)

    def run(self):
        self.listen()
        max_conn_num = self.app['MAX_CONNECTIONS']
        while not self.stop_event.is_set():
            try:
                client, addr = self.sock.accept()
                logger.info("Get ssh request from %s: %s" % (addr[0], addr[1]))
                if len(self.app.connections) >= max_conn_num:
                    client.close()
                    logger.warning("Arrive max connection number %s, "
                                   "reject new request %s:%s" %
                                   (max_conn_num, addr[0], addr[1]))
                else:
                    self.app.connections.append((client, addr))
                thread = threading.Thread(target=self.handle, args=(client, addr))
                thread.daemon = True
                thread.start()
            except Exception as e:
                logger.error("SSH server error: %s" % e)

    def handle(self, client, addr):
        transport = paramiko.Transport(client, gss_kex=False)
        try:
            transport.load_server_moduli()
        except IOError:
            logger.warning("Failed load moduli -- gex will be unsupported")

        transport.add_server_key(self.host_key)
        request = Request(client, addr)
        server = SSHInterface(self.app, request)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            logger.warning("SSH negotiation failed.")
            sys.exit(1)

        chan = transport.accept(10)
        if chan is None:
            logger.warning("No ssh channel get")
            sys.exit(1)

        server.event.wait(5)
        if not server.event.is_set():
            logger.warning("Client not request a valid request")
            sys.exit(2)

        self.dispatch(request, chan)

    def dispatch(self, request, channel):
        if request.type == 'pty':
            pass
        elif request.type == 'exec':
            pass
        elif request.type == 'subsystem':
            pass
        else:
            channel.send("Not support request type: %s" % request.type)

    def shutdown(self):
        self.stop_event.set()
