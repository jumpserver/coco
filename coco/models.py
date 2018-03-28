#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import threading
import datetime
import weakref
import time

from . import char
from . import utils

BUF_SIZE = 4096
logger = utils.get_logger(__file__)


class Request:
    def __init__(self, addr):
        self.type = []
        self.meta = {"width": 80, "height": 24}
        self.user = None
        self.addr = addr
        self.remote_ip = self.addr[0]
        self.change_size_event = threading.Event()
        self.date_start = datetime.datetime.now()

    # def __del__(self):
    #     print("GC: Request object gc")


class SizedList(list):
    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self.size = 0
        super().__init__()

    def append(self, b):
        if self.maxsize == 0 or self.size < self.maxsize:
            super().append(b)
            self.size += len(b)

    def clean(self):
        self.size = 0
        del self[:]


class Client:
    """
    Client is the request client. Nothing more to say

    ```
    client = Client(chan, addr, user)
    ```
    """

    def __init__(self, chan, request):
        self.chan = chan
        self.request = request
        self.user = request.user
        self.addr = request.addr

    def fileno(self):
        return self.chan.fileno()

    def send(self, b):
        if isinstance(b, str):
            b = b.encode("utf-8")
        try:
            return self.chan.send(b)
        except OSError:
            self.close()
            return

    def recv(self, size):
        return self.chan.recv(size)

    def close(self):
        logger.info("Client {} close".format(self))
        return self.chan.close()

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<%s from %s:%s>" % (self.user, self.addr[0], self.addr[1])

    # def __del__(self):
    #     print("GC: Client object has been gc")


class Server:
    """
    Server object like client, a wrapper object, a connection to the asset,
    Because we don't want to using python dynamic feature, such asset
    have the chan and system_user attr.
    """

    # Todo: Server name is not very suitable
    def __init__(self, chan, asset, system_user):
        self.chan = chan
        self.asset = asset
        self.system_user = system_user
        self.send_bytes = 0
        self.recv_bytes = 0
        self.stop_evt = threading.Event()

        self.input_data = SizedList(maxsize=1024)
        self.output_data = SizedList(maxsize=1024)
        self._in_input_state = True
        self._input_initial = False
        self._in_vim_state = False

        self._input = ""
        self._output = ""
        self._session_ref = None

    def fileno(self):
        return self.chan.fileno()

    def set_session(self, session):
        self._session_ref = weakref.ref(session)

    @property
    def session(self):
        if self._session_ref:
            return self._session_ref()
        else:
            return None

    def parse(self, b):
        if isinstance(b, str):
            b = b.encode("utf-8")
        if not self._input_initial:
            self._input_initial = True

        if self._have_enter_char(b):
            self._in_input_state = False
            self._input = self._parse_input()
        else:
            if not self._in_input_state:
                self._output = self._parse_output()
                logger.debug("\n{}\nInput: {}\nOutput: {}\n{}".format(
                    "#" * 30 + " Command " + "#" * 30,
                    self._input, self._output,
                    "#" * 30 + " End " + "#" * 30,
                ))
                if self._input:
                    self.session.put_command(self._input, self._output)
                self.input_data.clean()
                self.output_data.clean()
            self._in_input_state = True

    def send(self, b):
        self.parse(b)
        return self.chan.send(b)

    def recv(self, size):
        data = self.chan.recv(size)
        self.session.put_replay(data)
        if self._input_initial:
            if self._in_input_state:
                self.input_data.append(data)
            else:
                self.output_data.append(data)
        return data

    def close(self):
        logger.info("Closed server {}".format(self))
        self.parse(b'')
        self.stop_evt.set()
        self.chan.close()
        self.chan.transport.close()

    @staticmethod
    def _have_enter_char(s):
        for c in char.ENTER_CHAR:
            if c in s:
                return True
        return False

    def _parse_output(self):
        if not self.output_data:
            return ''
        parser = utils.TtyIOParser()
        return parser.parse_output(self.output_data)

    def _parse_input(self):
        if not self.input_data or self.input_data[0] == char.RZ_PROTOCOL_CHAR:
            return
        parser = utils.TtyIOParser()
        return parser.parse_input(self.input_data)

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<To: {}>".format(str(self.asset))

    # def __del__(self):
    #     print("GC: Server object has been gc")


class WSProxy:
    """
    WSProxy is websocket proxy channel object.

    Because tornado or flask websocket base event, if we want reuse func
    with sshd, we need change it to socket, so we implement a proxy.

    we should use socket pair implement it. usage:

    ```

    child, parent = socket.socketpair()

    # self must have write_message method, write message to ws
    proxy = WSProxy(self, child)
    client = Client(parent, user)

    ```
    """

    def __init__(self, ws, child, room, connection):
        """
        :param ws: websocket instance or handler, have write_message method
        :param child: sock child pair
        """
        self.ws = ws
        self.child = child
        self.stop_event = threading.Event()
        self.room = room
        self.auto_forward()
        self.connection = connection

    def send(self, msg):
        """
        If ws use proxy send data, then send the data to child sock, then
        the parent sock recv

        :param msg: terminal write message {"data": "message"}
        :return:
        """
        data = msg["data"]
        if isinstance(data, str):
            data = data.encode('utf-8')
        self.child.send(data)

    def forward(self):
        while not self.stop_event.is_set():
            try:
                data = self.child.recv(BUF_SIZE)
            except OSError:
                continue
            if len(data) == 0:
                self.close()
            data = data.decode(errors="ignore")
            self.ws.emit("data", {'data': data, 'room': self.connection}, room=self.room)
            if len(data) == BUF_SIZE:
                time.sleep(0.1)

    def auto_forward(self):
        thread = threading.Thread(target=self.forward, args=())
        thread.daemon = True
        thread.start()

    def close(self):
        self.stop_event.set()
        self.child.close()
        self.ws.logout(self.connection)
        logger.debug("Proxy {} closed".format(self))




