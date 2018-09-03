#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import weakref
import uuid
import socket

from .struct import SizedList, SelectEvent
from . import char
from . import utils

BUF_SIZE = 4096
logger = utils.get_logger(__file__)


class Connection:
    connections = {}
    clients_num = 0

    def __init__(self, cid=None, sock=None, addr=None):
        if not cid:
            cid = str(uuid.uuid4())
        self.id = cid
        self.sock = sock
        self.addr = addr
        self.user = None
        self.otp_auth = False
        self.login_from = 'ST'
        self.clients = {}

    def __str__(self):
        return '<{} from {}>'.format(self.user, self.addr)

    def new_client(self, tid):
        client = Client(
            tid=tid, user=self.user, addr=self.addr,
            login_from=self.login_from
        )
        client.connection_id = self.id
        self.clients[tid] = client
        self.__class__.clients_num += 1
        logger.info("New client {} join, total {} now".format(
            client, self.__class__.clients_num
        ))
        return client

    def get_client(self, tid):
        if hasattr(tid, 'get_id'):
            tid = tid.get_id()
        client = self.clients.get(tid)
        return client

    def remove_client(self, tid):
        client = self.get_client(tid)
        if not client:
            return
        client.close()
        self.__class__.clients_num -= 1
        del self.clients[tid]
        logger.info("Client {} leave, total {} now".format(
            client, self.__class__.clients_num
        ))

    def close(self):
        clients_copy = [k for k in self.clients]
        for tid in clients_copy:
            self.remove_client(tid)
        self.sock.close()

    @classmethod
    def new_connection(cls, addr, sock=None, cid=None):
        if not cid:
            cid = str(uuid.uuid4())
        connection = cls(cid=cid, sock=sock, addr=addr)
        cls.connections[cid] = connection
        return connection

    @classmethod
    def remove_connection(cls, cid):
        connection = cls.get_connection(cid)
        connection.close()
        del cls.connections[cid]

    @classmethod
    def get_connection(cls, cid):
        return cls.connections.get(cid)


class Request:
    def __init__(self):
        self.type = None
        self.x11 = None
        self.kind = None
        self.meta = {'env': {}}


class Client:
    """
    Client is the request client. Nothing more to say

    ```
    client = Client(chan, addr, user)
    ```
    """

    def __init__(self, tid=None, user=None, addr=None, login_from=None):
        if tid is None:
            tid = str(uuid.uuid4())
        self.id = tid
        self.user = user
        self.addr = addr
        self.chan = None
        self.request = Request()
        self.connection_id = None
        self.login_from = login_from
        self.change_size_evt = SelectEvent()

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


class BaseServer:
    """
    Base Server
    Achieve command record
    sub-class: Server, Telnet Server
    """

    def __init__(self):
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
    def __init__(self, ws, client_id):
        self.ws = ws
        self.client_id = client_id
        self.sock, self.proxy = socket.socketpair()

    def send(self, data):
        _data = {'data': data.decode(errors="ignore"), 'room': self.client_id},
        self.ws.emit("data", _data, room=self.client_id)

    @property
    def closed(self):
        return self.sock._closed

    def session_close(self):
        self.ws.on_logout(self.client_id)

    def write(self, data):
        self.proxy.send(data.encode())

    def close(self):
        self.proxy.close()
        self.sock.close()

    def __getattr__(self, item):
        return getattr(self.sock, item)

