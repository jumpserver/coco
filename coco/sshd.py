#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import socket
import random
import multiprocessing
from multiprocessing.reduction import recv_handle, send_handle, DupFd
import threading

import paramiko

from .utils import ssh_key_gen, get_logger
from .interface import SSHInterface
from .interactive import InteractiveServer
from .models import Client, Request
from .sftp import SFTPServer
from .ctx import current_app

logger = get_logger(__file__)
BACKLOG = 5


class SSHServer:

    def __init__(self):
        self.stop_evt = threading.Event()
        self.workers = []
        self.pipe = None

    @property
    def host_key(self):
        host_key_path = os.path.join(current_app.root_path, 'keys', 'host_rsa_key')
        if not os.path.isfile(host_key_path):
            self.gen_host_key(host_key_path)
        return paramiko.RSAKey(filename=host_key_path)

    @staticmethod
    def gen_host_key(key_path):
        ssh_key, _ = ssh_key_gen()
        with open(key_path, 'w') as f:
            f.write(ssh_key)

    @staticmethod
    def start_master(in_p, out_p, workers):
        in_p.close()
        host = current_app.config["BIND_HOST"]
        port = current_app.config["SSHD_PORT"]
        print('Starting ssh server at {}:{}'.format(host, port))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        sock.bind((host, port))
        sock.listen(BACKLOG)
        while True:
            try:
                client, addr = sock.accept()
                logger.info("Get ssh request from {}: {}".format(*addr))
                worker = random.choice(workers)
                send_handle(out_p, client.fileno(), worker.pid)
                client.close()
            except IndexError as e:
                logger.error("Start SSH server error: {}".format(e))

    def start_workers(self, in_p, out_p):
        workers = []
        for i in range(4):
            worker = multiprocessing.Process(
                target=self.start_worker, args=(in_p, out_p)
            )
            worker.daemon = True
            workers.append(worker)
            worker.start()
        return workers

    def start_worker(self, in_p, out_p):
        out_p.close()
        while True:
            fd = recv_handle(in_p)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, fileno=fd)
            # print("Recv sock: {}".format(sock))
            addr = sock.getpeername()
            thread = threading.Thread(
                target=self.handle_connection, args=(sock, addr)
            )
            thread.daemon = True
            thread.start()

    def run(self):
        c1, c2 = multiprocessing.Pipe()
        workers = self.start_workers(c1, c2)
        server_p = multiprocessing.Process(
            target=self.start_master, args=(c1, c2, workers), name='master'
        )
        server_p.start()
        c1.close()
        c2.close()

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
        server = SSHInterface(request)
        try:
            transport.start_server(server=server)
        except paramiko.SSHException:
            logger.warning("SSH negotiation failed")
            return
        except EOFError as e:
            logger.warning("Handle EOF Error: {}".format(e))
            return
        print("3333334")
        while True:
            if not transport.is_active():
                print("IS closed")
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
        current_app.add_client(client)
        self.dispatch(client)

    @staticmethod
    def dispatch(client):
        supported = {'pty', 'x11', 'forward-agent'}
        request_type = set(client.request.type)
        if supported & request_type:
            logger.info("Request type `pty`, dispatch to interactive mode")
            InteractiveServer(client).interact()
        elif 'subsystem' in request_type:
            pass
        else:
            logger.info("Request type `{}`".format(request_type))
            client.send("Not support request type: %s" % request_type)

    def shutdown(self):
        self.stop_evt.set()
