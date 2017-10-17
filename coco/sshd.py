#! coding: utf-8

import logging
import socket

logger = logging.getLogger(__file__)
BACKLOG = 5


class SSHServer:

    def __init__(self, app=None):
        self.app = app

    def run(self):
        host = self.app.config["BIND_HOST"]
        port = self.app.config["SSHD_PORT"]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(BACKLOG)
        print('Starting ssh server at %(host)s:%(port)s' %
              {"host": host, "port": port})


    def shutdown(self):
        pass
