import json
import queue
import threading
import datetime
import logging

from . import char
from . import utils

BUF_SIZE = 4096
logger = logging.getLogger(__file__)


class Request:
    def __init__(self, addr):
        self.type = ""
        self.meta = {}
        self.user = None
        self.addr = addr
        self.remote_ip = self.addr[0]
        self.change_size_event = threading.Event()
        self.date_start = datetime.datetime.now()


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
        return self.chan.send(b)

    def recv(self, size):
        return self.chan.recv(size)

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<%s from %s:%s>" % (self.user, self.addr[0], self.addr[1])


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

        self.input_data = []
        self.output_data = []
        self._in_input_state = True
        self._input_initial = False
        self._in_vim_state = False

        self.recorders = []
        self.filters = []
        self._input = ""
        self._output = ""
        self.command_queue = queue.Queue()

    def add_recorder(self, recorder):
        self.recorders.append(recorder)

    def remove_recorder(self, recorder):
        self.recorders.remove(recorder)

    def add_filter(self, _filter):
        self.filters.append(_filter)

    def remove_filter(self, _filter):
        self.filters.remove(_filter)

    def record_command_async(self):
        def func():
            while not self.stop_evt.is_set():
                _input, _output = self.command_queue.get()
                for recorder in self.recorders:
                    recorder.record_command(datetime.datetime.now(), _input, _output)
        thread = threading.Thread(target=func)
        thread.start()

    def fileno(self):
        return self.chan.fileno()

    def send(self, b):
        if isinstance(b, str):
            b = b.encode("utf-8")
        if not self._input_initial:
            self._input_initial = True

        if self._have_enter_char(b):
            self._in_input_state = False
            self._input = self._parse_input()
        else:
            if not self._in_input_state:
                print("#" * 30 + " 新周期 " + "#" * 30)
                self._output = self._parse_output()
                print(self._input)
                print(self._output)
                print("#" * 30 + " End " + "#" * 30)
                self.command_queue.put((self._input, self._output))
                del self.input_data[:]
                del self.output_data[:]
                self._input = ""
                self._output = ""
            self._in_input_state = True
        return self.chan.send(b)

    def recv(self, size):
        data = self.chan.recv(size)
        if self._input_initial:
            if self._in_input_state:
                self.input_data.append(data)
            else:
                self.output_data.append(data)
        return data

    def close(self):
        self.chan.close()
        return self.chan.transport.close()

    @staticmethod
    def _have_enter_char(s):
        for c in char.ENTER_CHAR:
            if c in s:
                return True
        return False

    def _parse_output(self):
        parser = utils.TtyIOParser()
        return parser.parse_output(self.output_data)

    def _parse_input(self):
        parser = utils.TtyIOParser()
        return parser.parse_input(self.input_data)

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<%s@%s:%s>" % (self.system_user.username,
                               self.asset.hostname,
                               self.asset.port)


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

    def __init__(self, ws, child):
        """
        :param ws: websocket instance or handler, have write_message method
        :param child: sock child pair
        """
        self.ws = ws
        self.child = child
        self.stop_event = threading.Event()

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
            data = self.child.recv(BUF_SIZE)
            if len(data) == 0:
                self.close()
            self.ws.write_message(json.dumps({"data": data.decode("utf-8")}))

    def auto_forward(self):
        thread = threading.Thread(target=self.forward, args=())
        thread.daemon = True
        thread.start()

    def close(self):
        self.stop_event.set()
        self.ws.close()
        self.child.close()
