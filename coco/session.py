#!coding: utf-8

import select
import uuid
import socket
import logging
import datetime
import selectors


BUF_SIZE = 1024
logger = logging.getLogger(__file__)


class Session:

    def __init__(self, client, server):
        self.id = str(uuid.uuid4())
        self.client = client  # Master of the session, it's a client sock
        self.server = server  # Server channel
        self.watchers = []  # Only watch session
        self.sharers = []  # Join to the session, read and write
        self.running = True
        self.date_created = datetime.datetime.now()
        self.date_finished = None
        self.sel = selectors.DefaultSelector()

    def add_watcher(self, watcher):
        """
        Add a watcher, and will be transport server side msg to it.

        :param watcher: A client socket
        :return:
        """
        logger.info("Session % add watcher %s" % (self, watcher))
        watcher.send("Welcome to join session %s\r\n" % self.id)
        self.sel.register(watcher, selectors.EVENT_READ)
        self.watchers.append(watcher)

    def remove_watcher(self, watcher):
        logger.info("Session %s remove watcher %s" % (self, watcher))
        watcher.send("Leave session %s at %s" % (self.id, datetime.datetime.now()))
        self.sel.unregister(watcher)
        self.watchers.remove(watcher)

    def add_sharer(self, sharer):
        """
        Add a sharer, it can read and write to server
        :param sharer:  A client socket
        :return:
        """
        logger.info("Session %s add share %s" % (self.id, sharer))
        sharer.send("Welcome to join session %s\r\n" % self.id)
        self.sel.register(sharer, selectors.EVENT_READ)
        self.sharers.append(sharer)

    def remove_sharer(self, sharer):
        logger.info("Session %s remove sharer %s" % (self.id, sharer))
        sharer.send("Leave session %s at %s" % (self.id, datetime.datetime.now()))
        self.sel.unregister(sharer)
        self.sharers.remove(sharer)

    def bridge(self):
        """
        Bridge clients with server
        :return:

        """
        logger.info("Start bridge session %s" % self.id)
        self.sel.register(self.client, selectors.EVENT_READ)
        self.sel.register(self.server, selectors.EVENT_READ)
        while self.running:
            events = self.sel.select()
            for sock in [key.fileobj for key, _ in events]:
                data = sock.recv(BUF_SIZE)
                if sock == self.server:
                    if len(data) == 0:
                        self.close()
                        break
                    for watcher in [self.client] + self.watchers + self.sharers:
                        watcher.send(data)
                elif sock == self.client:
                    if len(data) == 0:
                        for watcher in self.watchers + self.sharers:
                            watcher.send("Client %s close the session" % self.client)
                        self.close()
                        break
                    self.server.send(data)
                elif sock in self.sharers:
                    if len(data) == 0:
                        logger.info("Sharer %s leave session %s" % (sock, self.id))
                        self.remove_sharer(sock)
                    self.server.send(data)
                elif sock in self.watchers:
                    if len(data) == 0:
                        logger.info("Watcher %s leave session %s" % (sock, self.id))

    def set_size(self, width, height):
        self.server.resize_pty(width=width, height=height)

    def record(self):
        """
        Record the session to a file. Using it replay in the future
        :return:
        """
        parent, child = socket.socketpair()
        self.add_watcher(parent)

    def replay(self):
        pass

    def close(self):
        self.running = False
        self.server.close()
        return

    def __str__(self):
        return self.id
    __repr__ = __str__





