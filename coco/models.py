#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import threading
import datetime
import weakref
import time
import builtins

from . import char
from . import utils
from .utils import trans_en, trans_zh
from .ctx import current_app

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
        self.trans = self.get_default_trans()
        self.gettext = self.trans_install()

    # def __del__(self):
    #     print("GC: Request object gc")

    @staticmethod
    def get_default_trans():
        lang = current_app.config['LANGUAGE_CODE']
        trans = [trans_zh, trans_en]
        if lang == 'en':
            trans[0], trans[1] = trans[1], trans[0]
        return trans

    def trans_install(self):
        self.trans[0].install()
        self.trans[0], self.trans[1] = self.trans[1], self.trans[0]
        self.gettext = builtins.__dict__['_']
        return self.gettext


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


class BaseServer:
    """
    Base Server
    Achieve command record
    sub-class: Server, Telnet Server
    """

    def __init__(self):
        self.stop_evt = threading.Event()
        self.chan = None

        self.input_data = SizedList(maxsize=1024)
        self.output_data = SizedList(maxsize=1024)
        self._in_input_state = True
        self._input_initial = False
        self._in_vim_state = False

        self._input = ""
        self._output = ""
        self._session_ref = None
        self._zmodem_recv_start_mark = b'rz waiting to receive.**\x18B0100'
        self._zmodem_send_start_mark = b'**\x18B00000000000000'
        self._zmodem_cancel_mark = b'\x18\x18\x18\x18\x18'
        self._zmodem_end_mark = b'**\x18B0800000000022d'
        self._zmodem_state_send = 'send'
        self._zmodem_state_recv = 'recv'
        self._zmodem_state = ''

    def set_session(self, session):
        self._session_ref = weakref.ref(session)

    @property
    def session(self):
        if self._session_ref:
            return self._session_ref()
        else:
            return None

    def initial_filter(self):
        if not self._input_initial:
            self._input_initial = True

    def parse_cmd_filter(self, data):
        # 输入了回车键, 开始计算输入的内容
        if self._have_enter_char(data):
            self._in_input_state = False
            self._input = self._parse_input()
            return data
        # 用户输入了内容，但是如果没在输入状态，也就是用户刚开始输入了，结算上次输出内容
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
        return data

    def send(self, data):
        self.initial_filter()
        self.parse_cmd_filter(data)
        return self.chan.send(data)

    def replay_filter(self, data):
        if not self._zmodem_state:
            self.session.put_replay(data)

    def input_output_filter(self, data):
        if not self._input_initial:
            return
        if self._zmodem_state:
            return
        if self._in_input_state:
            self.input_data.append(data)
        else:
            self.output_data.append(data)

    def zmodem_state_filter(self, data):
        if not self._zmodem_state:
            if data[:50].find(self._zmodem_recv_start_mark) != -1:
                logger.debug("Zmodem state => recv")
                self._zmodem_state = self._zmodem_state_recv
            elif data[:24].find(self._zmodem_send_start_mark) != -1:
                logger.debug("Zmodem state => send")
                self._zmodem_state = self._zmodem_state_send
        if self._zmodem_state:
            if data[:24].find(self._zmodem_end_mark) != -1:
                logger.debug("Zmodem state => end")
                self._zmodem_state = ''
            elif data[:24].find(self._zmodem_cancel_mark) != -1:
                logger.debug("Zmodem state => cancel")
                self._zmodem_state = ''

    def zmodem_cancel_filter(self):
        if self._zmodem_state:
            pass
            # self.chan.send(self._zmodem_cancel_mark)
            # self.chan.send("Zmodem disabled")

    def recv(self, size):
        data = self.chan.recv(size)
        self.zmodem_state_filter(data)
        self.zmodem_cancel_filter()
        self.replay_filter(data)
        self.input_output_filter(data)
        return data

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
        if not self.input_data:
            return
        parser = utils.TtyIOParser()
        return parser.parse_input(self.input_data)

    def fileno(self):
        return self.chan.fileno()

    def close(self):
        logger.info("Closed server {}".format(self))
        self.input_output_filter(b'')
        self.stop_evt.set()
        self.chan.close()

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<To: {}>".format(str(self.asset))


class TelnetServer(BaseServer):
    """
    Telnet server
    """
    def __init__(self, sock, asset, system_user):
        super(TelnetServer, self).__init__()
        self.chan = sock
        self.asset = asset
        self.system_user = system_user


class Server(BaseServer):
    """
    SSH Server
    Server object like client, a wrapper object, a connection to the asset,
    Because we don't want to using python dynamic feature, such asset
    have the chan and system_user attr.
    """

    # Todo: Server name is not very suitable
    def __init__(self, chan, sock, asset, system_user):
        super(Server, self).__init__()
        self.chan = chan
        self.sock = sock
        self.asset = asset
        self.system_user = system_user

    def close(self):
        super().close()
        self.chan.transport.close()
        if self.sock:
            self.sock.transport.close()


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

    def __init__(self, ws, child, room_id):
        """
        :param ws: websocket instance or handler, have write_message method
        :param child: sock child pair
        """
        self.ws = ws
        self.child = child
        self.stop_event = threading.Event()
        self.room_id = room_id
        self.auto_forward()

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
            except (OSError, EOFError):
                self.close()
                break
            if not data:
                self.close()
                break
            data = data.decode(errors="ignore")
            self.ws.emit("data", {'data': data, 'room': self.room_id},
                         room=self.room_id)
            if len(data) == BUF_SIZE:
                time.sleep(0.1)

    def auto_forward(self):
        thread = threading.Thread(target=self.forward, args=())
        thread.daemon = True
        thread.start()

    def close(self):
        self.ws.emit("logout", {"room": self.room_id}, room=self.room_id)
        self.stop_event.set()
        try:
            self.child.shutdown(1)
            self.child.close()
        except (OSError, EOFError):
            pass
        logger.debug("Proxy {} closed".format(self))

