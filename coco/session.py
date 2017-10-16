#!coding: utf-8

import select
import uuid
import socket

BUF_SIZE = 1024

logger =

class Session:

    def __init__(self, client, server):
        self.id = str(uuid.uuid4())
        self.client = client  # Master of the session, it's a client sock
        self.server = server  # Server channel
        self.watchers = []  # Only watch session
        self.sharers = []  # Join to the session, read and write
        self.running = True

    def add_watcher(self, watcher):
        """
        Add a watcher, and will be transport server side msg to it.

        :param watcher: A client socket
        :return:
        """
        self.watchers.append(watcher)

    def add_sharer(self, sharer):
        """
        Add a sharer, it can read and write to server
        :param sharer:  A client socket
        :return:
        """
        self.sharers.append(sharer)

    def bridge(self):
        """
        Bridge clients with server
        :return:

        """

        while self.running:
            try:
                r, w, x = select.select([self.client + self.server]
                                + self.watchers + self.sharers, [], [])

                for sock in r:
                    if sock == self.server:
                        data = sock.recv(BUF_SIZE)
                        if len(data) == 0:
                            self.close()
                        for watcher in [self.client] + self.watchers + self.sharers:
                            watcher.send(data)
                    elif sock == self.client:
                        data = sock.recv(BUF_SIZE)
                        if len(data) == 0:
                            for watcher in self.watchers + self.sharers:
                                watcher.send("%s close the session" % self.client)
                            self.close()
                        self.server.send(data)
                    elif sock in self.watchers:
                        sock.send("WARN: Your didn't have the write permission\r\n")
                    elif sock in self.sharers:
                        data = sock.recv(BUF_SIZE)
                        if len(data) == 0:
                            sock.send("Leave session %s" % self.id)
                        self.server.send(data)

            except Exception as e:
                pass

    def set_size(self, width, height):
        self.server.resize_pty(width=width, height=height)

    def record(self):
        parent, child = socket.socketpair()
        self.add_watcher(parent)


    def close(self):
        pass






