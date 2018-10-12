#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import uuid
import datetime
import selectors
import time

from .utils import get_logger, wrap_with_warning as warn, \
    wrap_with_line_feed as wr, ugettext as _, ignore_error
from .ctx import app_service
from .struct import SelectEvent
from .recorder import get_recorder

BUF_SIZE = 1024
logger = get_logger(__file__)


class Session:
    sessions = {}

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
        self.closed = False
        self.sel = selectors.DefaultSelector()
        self._command_recorder = None
        self._replay_recorder = None
        self.stop_evt = SelectEvent()
        self.server.set_session(self)
        self.date_last_active = datetime.datetime.utcnow()

    @classmethod
    def new_session(cls, client, server):
        session = cls(client, server)
        command_recorder, replay_recorder = get_recorder()
        session.set_command_recorder(command_recorder)
        session.set_replay_recorder(replay_recorder)
        cls.sessions[session.id] = session
        app_service.create_session(session.to_json())
        return session

    @classmethod
    def get_session(cls, sid):
        return cls.sessions.get(sid)

    @classmethod
    def remove_session(cls, sid):
        session = cls.get_session(sid)
        if session:
            session.close()
            app_service.finish_session(session.to_json())
            app_service.finish_replay(sid)
            del cls.sessions[sid]

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
        self._replay_recorder.record({
            "session": self.id,
            "data": data,
            "timestamp": time.time(),
        })

    def pre_bridge(self):
        self._replay_recorder.session_start(self.id)
        self._command_recorder.session_start(self.id)

    def post_bridge(self):
        self._replay_recorder.session_end(self.id)
        self._command_recorder.session_end(self.id)

    def terminate(self, msg=None):
        if not msg:
            msg = _("Terminated by administrator")
        try:
            self.client.send(wr(warn(msg), before=1))
        except OSError:
            pass
        self.stop_evt.set()

    def send_to_clients(self, data):
        for watcher in [self.client] + self._watchers + self._sharers:
            watcher.send(data)

    def bridge(self):
        """
        Bridge clients with server
        :return:
        """
        logger.info("Start bridge session: {}".format(self.id))
        self.pre_bridge()
        self.sel.register(self.client, selectors.EVENT_READ)
        self.sel.register(self.server, selectors.EVENT_READ)
        self.sel.register(self.stop_evt, selectors.EVENT_READ)
        self.sel.register(self.client.change_size_evt, selectors.EVENT_READ)
        while not self.is_finished:
            events = self.sel.select(timeout=60)
            for sock in [key.fileobj for key, _ in events]:
                data = sock.recv(BUF_SIZE)
                if sock == self.server:
                    if len(data) == 0:
                        msg = "Server close the connection"
                        logger.info(msg)
                        self.is_finished = True
                        break

                    self.date_last_active = datetime.datetime.utcnow()
                    for watcher in [self.client] + self._watchers + self._sharers:
                        watcher.send(data)
                elif sock == self.client:
                    if len(data) == 0:
                        msg = "Client close the connection: {}".format(self.client)
                        logger.info(msg)
                        for watcher in self._watchers + self._sharers:
                            watcher.send(msg.encode("utf-8"))
                        self.is_finished = True
                        break
                    self.server.send(data)
                elif sock == self.stop_evt:
                    self.is_finished = True
                    break
                elif sock == self.client.change_size_evt:
                    self.resize_win_size()
        logger.info("Session stop event set: {}".format(self.id))

    def resize_win_size(self):
        width, height = self.client.request.meta['width'], \
                        self.client.request.meta['height']
        logger.debug("Resize server chan size {}*{}".format(width, height))
        self.server.resize_pty(width=width, height=height)

    @ignore_error
    def close(self):
        if self.closed:
            logger.info("Session has been closed: {} ".format(self.id))
            return
        logger.info("Close the session: {} ".format(self.id))
        self.is_finished = True
        self.closed = True
        self.post_bridge()
        self.date_end = datetime.datetime.utcnow()

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
