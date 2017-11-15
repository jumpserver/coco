#!coding: utf-8

import os
import threading
import uuid
import socket
import logging
import datetime
import time
import selectors


BUF_SIZE = 1024
logger = logging.getLogger(__file__)


class Session:

    def __init__(self, client, server, session_dir):
        self.id = str(uuid.uuid4())
        self.client = client  # Master of the session, it's a client sock
        self.server = server  # Server channel
        self.session_dir = session_dir  # Dir to save session record
        self.watchers = []  # Only watch session
        self.sharers = []   # Join to the session, read and write
        self.stop_evt = threading.Event()
        self.replaying = True
        self.date_created = datetime.datetime.now()
        self.date_finished = None
        self.sel = selectors.DefaultSelector()

    def add_watcher(self, watcher, silent=False):
        """
        Add a watcher, and will be transport server side msg to it.

        :param watcher: A client socket
        :param silent: If true not send welcome message
        :return:
        """
        logger.info("Session %s add watcher %s" % (self, watcher))
        if not silent:
            watcher.send("Welcome to watch session {}\r\n".format(self.id).encode("utf-8"))
        self.sel.register(watcher, selectors.EVENT_READ)
        self.watchers.append(watcher)

    def remove_watcher(self, watcher):
        logger.info("Session %s remove watcher %s" % (self, watcher))
        self.sel.unregister(watcher)
        self.watchers.remove(watcher)

    def add_sharer(self, sharer, silent=False):
        """
        Add a sharer, it can read and write to server
        :param sharer:  A client socket
        :param silent: If true not send welcome message
        :return:
        """
        logger.info("Session %s add share %s" % (self.id, sharer))
        if not silent:
            sharer.send("Welcome to join session {}\r\n"
                        .format(self.id).encode("utf-8"))
        self.sel.register(sharer, selectors.EVENT_READ)
        self.sharers.append(sharer)

    def remove_sharer(self, sharer):
        logger.info("Session %s remove sharer %s" % (self.id, sharer))
        sharer.send("Leave session {} at {}"
                    .format(self.id, datetime.datetime.now()).encode("utf-8"))
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
        while not self.stop_evt.is_set():
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
                            watcher.send("Client {} close the session".format(self.client).encode("utf-8"))
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
        logger.info("Start record session %s" % self.id)
        parent, child = socket.socketpair()
        self.add_watcher(parent)
        record_dir = os.path.join(self.session_dir, self.date_created.strftime("%Y-%m-%d"))
        if not os.path.isdir(record_dir):
            os.mkdir(record_dir)
        with open(os.path.join(record_dir, self.id + ".rec"), 'wb') as dataf, \
            open(os.path.join(record_dir, self.id + ".time"), "w") as timef:
            dataf.write("Script started on {}\n".format(time.asctime()).encode("utf-8"))

            while not self.stop_evt.is_set():
                start_t = time.time()
                data = child.recv(BUF_SIZE)
                end_t = time.time()
                size = len(data)
                if size == 0:
                    break
                timef.write("%.4f %s\n" % (end_t-start_t, size))
                dataf.write(data)
            dataf.write("Script done on {}\n".format(time.asctime()).encode("utf-8"))
        logger.info("End session record %s" % self.id)

    def record_async(self):
        thread = threading.Thread(target=self.record)
        thread.start()

    def replay(self):
        """
        Replay the session
        :return:
        """
        with open(os.path.join(self.session_dir, self.id + ".rec"), 'rb') as dataf, \
               open(os.path.join(self.session_dir, self.id + ".time"), "r") as timef:

            self.client.send(dataf.readline())
            for l in timef:
                if not self.replaying:
                    break
                t, size = float(l.split()[0]), int(l.split()[1])
                data = dataf.read(size)
                time.sleep(t)
                self.client.send(data)
        self.client.send("Replay session {} end".format(self.id).encode('utf-8'))
        self.replaying = False

    def replay_download(self):
        """
        Using termrecord generate html, then down user download it and share it
        :return:
        """
        pass

    def close(self):
        self.stop_evt.set()
        self.date_finished = datetime.datetime.now()
        self.server.close()

    def to_json(self):
        return {
            "id": self.id,
            "user": self.client.user.username,
            "asset": self.server.asset.hostname,
            "system_user": self.server.system_user.username,
            "login_from": "ST",
            "is_finished": True if self.stop_evt.is_set() else False,
            "date_start": self.date_created.strftime("%Y-%m-%d %H:%M:%S"),
            "date_finished": self.date_finished.strftime("%Y-%m-%d %H:%M:%S") if self.date_finished else None
        }

    def __str__(self):
        return self.id

    def __repr__(self):
        return self.id





