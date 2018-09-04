#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import socket
import threading

import paramiko

from .utils import ssh_key_gen, get_logger
from .interface import SSHInterface
from .interactive import InteractiveServer
from .models import Connection
from .sftp import SFTPServer
from .config import config

logger = get_logger(__file__)
BACKLOG = 5


class SSHServer:

    def __init__(self):
        self.stop_evt = threading.Event()
        self.workers = []
        self.pipe = None
        self.connections = []

    @property
    def host_key(self):
        host_key_path = os.path.join(config['ROOT_PATH'], 'keys', 'host_rsa_key')
        if not os.path.isfile(host_key_path):
            self.gen_host_key(host_key_path)
        return paramiko.RSAKey(filename=host_key_path)

    @staticmethod
    def gen_host_key(key_path):
        ssh_key, _ = ssh_key_gen()
        with open(key_path, 'w') as f:
            f.write(ssh_key)

    def run(self):
        host = config["BIND_HOST"]
        port = config["SSHD_PORT"]
        print('Starting ssh server at {}:{}'.format(host, port))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        sock.bind((host, port))
        sock.listen(BACKLOG)
        while not self.stop_evt.is_set():
            try:
                client, addr = sock.accept()
                t = threading.Thread(target=self.handle_connection, args=(client, addr))
                t.daemon = True
                t.start()
            except IndexError as e:
                logger.error("Start SSH server error: {}".format(e))

    def new_connection(self, addr, sock):
        connection = Connection.new_connection(addr=addr, sock=sock)
        self.connections.append(connection)
        return connection

    def handle_connection(self, sock, addr):
        transport = paramiko.Transport(sock, gss_kex=False)
        try:
            transport.load_server_moduli()
        except IOError:
            logger.warning("Failed load moduli -- gex will be unsupported")

        transport.add_server_key(self.host_key)
        transport.set_subsystem_handler(
            'sftp', paramiko.SFTPServer, SFTPServer
        )
        connection = self.new_connection(addr, sock=sock)
        server = SSHInterface(connection)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            logger.warning("SSH negotiation failed")
            return
        except EOFError as e:
            logger.warning("Handle EOF Error: {}".format(e))
            return
        while transport.is_active():
            chan = transport.accept()
            server.event.wait(5)
            if chan is None:
                continue

            if not server.event.is_set():
                logger.warning("Client not request a valid request, exiting")
                sock.close()
                return
            else:
                server.event.clear()

            client = connection.clients.get(chan.get_id())
            client.chan = chan
            t = threading.Thread(target=self.dispatch, args=(client,))
            t.daemon = True
            t.start()
        Connection.remove_connection(connection.id)

    @staticmethod
    def dispatch(client):
        supported = {'pty', 'x11', 'forward-agent'}
        chan_type = client.request.type
        kind = client.request.kind
        if kind == 'session' and chan_type in supported:
            logger.info("Request type `{}:{}`, dispatch to interactive mode".format(kind, chan_type))
            InteractiveServer(client).interact()
            connection = Connection.get_connection(client.connection_id)
            connection.remove_client(client.id)
        elif chan_type == 'subsystem':
            pass
        else:
            msg = "Request type `{}:{}` not support now".format(kind, chan_type)
            logger.info(msg)
            client.send(msg)

    def shutdown(self):
        self.stop_evt.set()
