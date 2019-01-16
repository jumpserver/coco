#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import socket
import threading
import time

import paramiko

from coco.utils import ssh_key_gen, get_logger
from coco.interface import SSHInterface
from coco.interactive import InteractiveServer
from coco.models import Connection
from coco.sftp import SFTPServer
from coco.conf import config

logger = get_logger(__file__)
BACKLOG = 5


class SSHServer:

    def __init__(self):
        self.stop_evt = threading.Event()
        self.workers = []
        self.pipe = None

    @property
    def host_key(self):
        host_key_path = config['HOST_KEY_FILE']
        if not os.path.isfile(host_key_path):
            if config.HOST_KEY:
                with open(host_key_path, 'w') as f:
                    f.write(config.HOST_KEY)
            else:
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

    def handle_connection(self, sock, addr):
        logger.debug("Handle new connection from: {}".format(addr))
        transport = paramiko.Transport(sock, gss_kex=False)
        try:
            transport.load_server_moduli()
        except IOError:
            logger.warning("Failed load moduli -- gex will be unsupported")

        transport.add_server_key(self.host_key)
        transport.set_subsystem_handler(
            'sftp', paramiko.SFTPServer, SFTPServer
        )
        connection = Connection.new_connection(addr=addr, sock=sock)
        server = SSHInterface(connection)
        try:
            transport.start_server(server=server)
            while transport.is_active():
                chan = transport.accept()
                server.event.wait(5)
                if chan is None:
                    continue

                if not server.event.is_set():
                    logger.warning("Client not request invalid, exiting")
                    sock.close()
                    continue
                else:
                    server.event.clear()

                client = connection.clients.get(chan.get_id())
                client.chan = chan
                t = threading.Thread(target=self.dispatch, args=(client,))
                t.daemon = True
                t.start()
            transport.close()
        except paramiko.SSHException as e:
            logger.warning("SSH negotiation failed: {}".format(e))
        except EOFError as e:
            logger.warning("Handle connection EOF Error: {}".format(e))
        except Exception as e:
            logger.error("Unexpect error occur on handle connection: {}".format(e))
        finally:
            Connection.remove_connection(connection.id)
            sock.close()

    @staticmethod
    def dispatch(client):
        supported = {'pty', 'x11', 'forward-agent'}
        chan_type = client.request.type
        kind = client.request.kind
        try:
            if kind == 'session' and chan_type in supported:
                logger.info("Dispatch client to interactive mode")
                try:
                    InteractiveServer(client).interact()
                except IndexError as e:
                    logger.error("Unexpected error occur: {}".format(e))
            elif chan_type == 'subsystem':
                while not client.closed:
                    time.sleep(5)
                logger.debug("SFTP session finished")
            else:
                msg = "Request type `{}:{}` not support now".format(kind, chan_type)
                logger.error(msg)
                client.send_unicode(msg)
        finally:
            connection = Connection.get_connection(client.connection_id)
            if connection:
                connection.remove_client(client.id)

    def shutdown(self):
        self.stop_evt.set()


if __name__ == '__main__':
    ssh_server = SSHServer()
    ssh_server.run()
