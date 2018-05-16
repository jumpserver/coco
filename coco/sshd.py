#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import socket
import threading
import random
import paramiko
from multiprocessing.reduction import recv_handle, send_handle
from multiprocessing import Process, Pipe

from .utils import ssh_key_gen, get_logger, get_app
from .interface import SSHInterface
from .interactive import InteractiveServer
from .models import Client, Request
from .sftp import SFTPServer

logger = get_logger(__file__)
BACKLOG = 5


class SSHServer:

    def __init__(self):
        self.stop_evt = threading.Event()
        self.host_key_path = os.path.join(self.app.root_path, 'keys', 'host_rsa_key')
        self.workers = []
        self.pipe = None

    @property
    def app(self):
        return get_app()

    @property
    def host_key(self):
        if not os.path.isfile(self.host_key_path):
            self.gen_host_key()
        return paramiko.RSAKey(filename=self.host_key_path)

    def gen_host_key(self):
        ssh_key, _ = ssh_key_gen()
        with open(self.host_key_path, 'w') as f:
            f.write(ssh_key)

    def start_worker(self, in_pipe, out_pipe):
        print("APP: {}".format(self.app))
        print("APP sessions: {}".format(self.app))
        out_pipe.close()
        while not self.stop_evt.is_set():
            fd = recv_handle(in_pipe)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, fileno=fd)
            addr = sock.getpeername()
            thread = threading.Thread(target=self.handle_connection, args=(sock, addr))
            thread.daemon = True
            thread.start()

    def start_server(self, in_pipe, out_pipe, workers):
        in_pipe.close()
        host = self.app.config["BIND_HOST"]
        port = self.app.config["SSHD_PORT"]
        print('Starting ssh server at {}:{}'.format(host, port))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(BACKLOG)

        while not self.stop_evt.is_set():
            client, addr = sock.accept()
            logger.info("Get ssh request from {}".format(addr))
            send_handle(out_pipe, client.fileno(), random.choice(workers).pid)
            client.close()

    def run(self):
        in_pipe, out_pipe = Pipe()
        self.pipe = (in_pipe, out_pipe)
        workers = []
        for i in range(4):
            worker = Process(target=self.start_worker, args=(in_pipe, out_pipe))
            worker.start()
            workers.append(worker)
        self.start_server(in_pipe, out_pipe, workers)
        in_pipe.close()
        out_pipe.close()

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
        request = Request(addr)
        server = SSHInterface(self.app, request)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            logger.warning("SSH negotiation failed")
            return
        except EOFError:
            logger.warning("Handle EOF Error")
            return

        while True:
            if not transport.is_active():
                transport.close()
                sock.close()
                break
            chan = transport.accept()
            server.event.wait(5)

            if chan is None:
                continue

            if not server.event.is_set():
                logger.warning("Client not request a valid request, exiting")
                return

            t = threading.Thread(target=self.handle_chan, args=(chan, request))
            t.daemon = True
            t.start()

    def handle_chan(self, chan, request):
        client = Client(chan, request)
        self.app.add_client(client)
        self.dispatch(client)

    def dispatch(self, client):
        supported = {'pty', 'x11', 'forward-agent'}
        request_type = set(client.request.type)
        if supported & request_type:
            logger.info("Request type `pty`, dispatch to interactive mode")
            InteractiveServer(self.app, client).interact()
        elif 'subsystem' in request_type:
            pass
        else:
            logger.info("Request type `{}`".format(request_type))
            client.send("Not support request type: %s" % request_type)

    def shutdown(self):
        self.stop_evt.set()
