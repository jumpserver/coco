#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import uuid
import datetime
import selectors
import time

from .utils import get_logger, wrap_with_warning as warn, \
    wrap_with_line_feed as wr, ugettext as _, ignore_error
from .alignment import session_queue

BUF_SIZE = 1024
logger = get_logger(__file__)


class SessionManager:
    sessions = []

    @classmethod
    def create_session(cls, *args, **kwargs):
        session = Session(*args, **kwargs)
        session_queue.put('create', session.to_json())
        cls.sessions.append(session)
        return session


class Session:
    def __init__(self, client, server):
        self.id = str(uuid.uuid4())
        self.client = client  # Master of the session, it's a client sock
        self.server = server  # Server channel
        self._watchers = []  # Only watch session
        self._sharers = []  # Join to the session, read and write
        self.replaying = True
        self.date_start = datetime.datetime.utcnow()
        self.date_end = None
        self.is_finished = False
        # self.sel = selectors.DefaultSelector()
        self._command_recorder = None
        self._replay_recorder = None
        self.server.set_session(self)
        self.date_last_active = datetime.datetime.utcnow()

    def add_watcher(self, watcher, silent=False):
        """
        Add a watcher, and will be transport server side msg to it.

        :param watcher: A client socket
        :param silent: If true not send welcome message
        :return:
        """
        logger.info("Session add watcher: {} -> {} ".format(self.id, watcher))
        if not silent:
            watcher.send("Welcome to watch session {}\r\n".format(self.id).encode())
        self.sel.register(watcher, selectors.EVENT_READ)
        self._watchers.append(watcher)

    def remove_watcher(self, watcher):
        logger.info("Session %s remove watcher %s" % (self.id, watcher))
        self.sel.unregister(watcher)
        self._watchers.remove(watcher)

    def add_sharer(self, sharer, silent=False):
        """
        Add a sharer, it can read and write to server
        :param sharer:  A client socket
        :param silent: If true not send welcome message
        :return:
        """
        logger.info("Session %s add share %s" % (self.id, sharer))
        if not silent:
            sharer.send("Welcome to join session: {}\r\n"
                        .format(self.id).encode("utf-8"))
        self.sel.register(sharer, selectors.EVENT_READ)
        self._sharers.append(sharer)

    @property
    def closed_unexpected(self):
        return not self.is_finished and (self.client.closed or self.server.closed)

    def remove_sharer(self, sharer):
        logger.info("Session %s remove sharer %s" % (self.id, sharer))
        sharer.send("Leave session {} at {}"
                    .format(self.id, datetime.datetime.now())
                    .encode("utf-8"))
        self.sel.unregister(sharer)
        self._sharers.remove(sharer)

    def set_command_recorder(self, recorder):
        self._command_recorder = recorder

    def set_replay_recorder(self, recorder):
        self._replay_recorder = recorder

    def put_command(self, _input, _output):
        return
        if not _input:
            return
        self._command_recorder.record({
            "session": self.id,
            "org_id": self.server.asset.org_id,
            "input": _input,
            "output": _output,
            "user": self.client.user.username,
            "asset": self.server.asset.hostname,
            "system_user": self.server.system_user.username,
            "timestamp": time.time(),
        })

    def put_replay(self, data):
        return
        self._replay_recorder.record({
            "session": self.id,
            "data": data,
            "timestamp": time.time(),
        })

    def pre_bridge(self):
        pass
        # self._replay_recorder.session_start(self.id)
        # self._command_recorder.session_start(self.id)

    def post_bridge(self):
        pass
        # self._replay_recorder.session_end(self.id)
        # self._command_recorder.session_end(self.id)

    def terminate(self, msg=None):
        if not msg:
            msg = _("Terminated by administrator")
        try:
            self.client.send(wr(warn(msg), before=1))
        except OSError:
            pass
        self.close()
        self.client.close()

    def bridge(self):
        """
        Bridge clients with server
        :return:
        """
        logger.info("Start bridge session: {}".format(self.id))
        self.pre_bridge()
        sel = selectors.DefaultSelector()
        sel.register(self.client, selectors.EVENT_READ)
        sel.register(self.server, selectors.EVENT_READ)
        while not self.is_finished:
            events = sel.select(timeout=60)
            for sock in [key.fileobj for key, _ in events]:
                data = sock.recv(BUF_SIZE)
                # self.put_replay(data)
                if sock == self.server:
                    if len(data) == 0:
                        msg = "Server close the connection"
                        logger.info(msg)
                        self.close()
                        break

                    self.date_last_active = datetime.datetime.utcnow()
                    for watcher in [self.client] + self._watchers + self._sharers:
                        watcher.send(data)
                elif sock == self.client:
                    if len(data) == 0:
                        msg = "Channel close the connection: {}".format(self.client)
                        logger.info(msg)
                        for watcher in self._watchers + self._sharers:
                            watcher.send(msg.encode("utf-8"))
                        self.close()
                        break
                    self.server.send(data)
                elif sock in self._sharers:
                    if len(data) == 0:
                        logger.info("Sharer {} leave the session {}".format(sock, self.id))
                        self.remove_sharer(sock)
                    self.server.send(data)
                elif sock in self._watchers:
                    if len(data) == 0:
                        self._watchers.remove(sock)
                        logger.info("Watcher {} leave the session {}".format(sock, self.id))
        logger.info("Session stop event set: {}".format(self.id))

    def set_size(self, width, height):
        logger.debug("Resize server chan size {}*{}".format(width, height))
        self.server.resize_pty(width=width, height=height)

    @ignore_error
    def close(self):
        logger.info("Close the session: {} ".format(self.id))
        if self.is_finished:
            logger.info("Session has been closed: {} ".format(self.id))
            return
        self.is_finished = True
        self.post_bridge()
        self.date_end = datetime.datetime.utcnow()
        self.server.close()
        session_queue.put('delete', self.id)

    def to_json(self):
        return {
            "id": self.id,
            "user": self.client.user.username,
            "asset": self.server.asset.hostname,
            "org_id": self.server.asset.org_id,
            "system_user": self.server.system_user.username,
            "login_from": self.client.login_from,
            "remote_addr": self.client.addr[0],
            "is_finished": self.is_finished,
            "date_start": self.date_start.strftime("%Y-%m-%d %H:%M:%S") + " +0000",
            "date_end": self.date_end.strftime("%Y-%m-%d %H:%M:%S") + " +0000" if self.date_end else None
        }

    def __str__(self):
        return self.id

    def __repr__(self):
        return self.id

    # def __del__(self):
    #     print("GC: Session object has been GC")
