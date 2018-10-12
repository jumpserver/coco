#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import weakref
import uuid
import socket

from .service import app_service
from .struct import SizedList, SelectEvent
from .utils import wrap_with_line_feed as wr, wrap_with_warning as warning, \
    ugettext as _
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


class ServerFilter:
    def run(self, data):
        pass


class BaseServer:
    """
    Base Server
    Achieve command record
    sub-class: Server, Telnet Server
    """

    def __init__(self, chan=None):
        self.chan = chan
        self._session_ref = None

        self._pre_input_state = True
        self._in_input_state = True
        self._input_initial = False

        self._enter_vim_mark = b'\x1b[?25l\x1b[37;1H\x1b[1m'
        self._exit_vim_mark = b'\x1b[37;1H\x1b[K\x1b'
        self._in_vim_state = False

        self.input_data = SizedList(maxsize=1024)
        self.output_data = SizedList(maxsize=1024)
        self._input = ""
        self._output = ""

        self._zmodem_recv_start_mark = b'rz waiting to receive.**\x18B0100'
        self._zmodem_send_start_mark = b'**\x18B00000000000000'
        self._zmodem_cancel_mark = b'\x18\x18\x18\x18\x18'
        self._zmodem_end_mark = b'**\x18B0800000000022d'
        self._zmodem_state_send = 'send'
        self._zmodem_state_recv = 'recv'
        self._zmodem_state = ''

        self._cmd_parser = utils.TtyIOParser()
        self._cmd_filter_rules = self.get_system_user_cmd_filter_rules()

    def get_system_user_cmd_filter_rules(self):
        rules = app_service.get_system_user_cmd_filter_rules(
            self.system_user.id
        )
        return rules

    def set_session(self, session):
        self._session_ref = weakref.ref(session)

    @property
    def session(self):
        if self._session_ref:
            return self._session_ref()
        else:
            return None

    def s_initial_filter(self, data):
        if not self._input_initial:
            self._input_initial = True
        return data

    def s_input_state_filter(self, data):
        self._pre_input_state = self._in_input_state
        if self._in_vim_state:
            self._in_input_state = False
        # 输入了回车键
        elif self._have_enter_char(data):
            self._in_input_state = False
        else:
            self._in_input_state = True
        return data

    def s_parse_input_output_filter(self, data):
        # 输入了回车键, 计算输入的命令
        if not self._in_input_state:
            self._input = self._parse_input()
        # 用户输入了内容，但是上次没在输入状态，也就是用户刚开始输入了，结算上次输出内容
        if not self._pre_input_state and self._in_input_state:
            self._output = self._parse_output()
            # logger.debug("\n{}\nInput: {}\nOutput: {}\n{}".format(
            #     "#" * 30 + " Command " + "#" * 30,
            #     self._input, self._output,
            #     "#" * 30 + " End " + "#" * 30,
            # ))
            if self._input:
                self.session.put_command(self._input, self._output)
            self.input_data.clean()
            self.output_data.clean()
        return data

    def s_filter_cmd_filter(self, data):
        if self._in_input_state:
            return data
        for rule in self._cmd_filter_rules:
            action, cmd = rule.match(self._input)
            if action == rule.ALLOW:
                break
            elif action == rule.DENY:
                data = char.CLEAR_LINE_CHAR + b'\r\n'
                msg = _("Command `{}` is forbidden ........").format(cmd)
                msg = wr(warning(msg.encode()), before=1, after=1)
                self.output_data.append(msg)
                self.session.send_to_clients(msg)
                self.session.put_replay(msg)
                break
        return data

    def r_replay_filter(self, data):
        if not self._zmodem_state:
            self.session.put_replay(data)

    def r_vim_state_filter(self, data):
        if self._zmodem_state:
            return data
        if self._in_vim_state and data[:11] == self._exit_vim_mark:
            self._in_vim_state = False
        elif not self._in_vim_state and data[:17] == self._enter_vim_mark:
            self._in_vim_state = True
        return data

    def r_input_output_data_filter(self, data):
        if not self._input_initial:
            return data
        if self._zmodem_state:
            return data
        if self._in_input_state:
            self.input_data.append(data)
        else:
            self.output_data.append(data)
        return data

    def r_zmodem_state_filter(self, data):
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

    def r_zmodem_disable_filter(self, data=''):
        if self._zmodem_state:
            pass
            # self.chan.send(self._zmodem_cancel_mark)
            # self.chan.send("Zmodem disabled")

    def send(self, data):
        self.s_initial_filter(data)
        self.s_input_state_filter(data)
        try:
            self.s_parse_input_output_filter(data)
            data = self.s_filter_cmd_filter(data)
        except Exception as e:
            logger.exception(e)
        return self.chan.send(data)

    def recv(self, size):
        data = self.chan.recv(size)
        self.r_zmodem_state_filter(data)
        self.r_vim_state_filter(data)
        self.r_zmodem_disable_filter(data)
        self.r_replay_filter(data)
        self.r_input_output_data_filter(data)
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
        return self._cmd_parser.parse_output(self.output_data)

    def _parse_input(self):
        if not self.input_data:
            return
        return self._cmd_parser.parse_input(self.input_data)

    def fileno(self):
        return self.chan.fileno()

    def close(self):
        logger.info("Closed server {}".format(self))
        self.r_input_output_data_filter(b'')
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
        self.asset = asset
        self.system_user = system_user
        super(TelnetServer, self).__init__(chan=sock)


class Server(BaseServer):
    """
    SSH Server
    Server object like client, a wrapper object, a connection to the asset,
    Because we don't want to using python dynamic feature, such asset
    have the chan and system_user attr.
    """

    # Todo: Server name is not very suitable
    def __init__(self, chan, sock, asset, system_user):
        self.sock = sock
        self.asset = asset
        self.system_user = system_user
        super(Server, self).__init__(chan=chan)

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

    def write(self, data):
        self.proxy.send(data.encode())

    def close(self):
        self.proxy.close()

    def __getattr__(self, item):
        return getattr(self.sock, item)

