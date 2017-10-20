import json
import threading

import select


BUF_SIZE = 4096


class Decoder:
    def __init__(self, **kwargs):
        for attr, val in kwargs.items():
            setattr(self, attr, val)

    @classmethod
    def from_json(cls, json_str):
        json_dict = json.loads(json_str)
        return cls(**json_dict)

    @classmethod
    def from_multi_json(cls, json_list):
        json_dict_list = json.loads(json_list)
        return [cls(**json_dict) for json_dict in json_dict_list]


class User(Decoder):
    id = ""
    username = ""
    name = ""

    def __str__(self):
        return self.name
    __repr__ = __str__


class Asset(Decoder):
    id = ""
    hostname = ""
    ip = ""
    port = 22

    def __str__(self):
        return self.hostname
    __repr__ = __str__


class SystemUser(Decoder):
    id = ""
    name = ""
    username = ""
    password = ""
    private_key = ""

    def __str__(self):
        return self.name
    __repr__ = __str__


class Client:
    """
    Client is the request client. Nothing more to say

    ```
    client = Client(chan, addr, user)
    ```

    """

    def __init__(self, chan, addr, user):
        self.chan = chan
        self.addr = addr
        self.user = user

    def fileno(self):
        return self.chan.fileno()

    def send(self, b):
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
    # Todo: Server name is not very proper
    def __init__(self, chan, asset, system_user):
        self.chan = chan
        self.asset = asset
        self.system_user = system_user

    def fileno(self):
        return self.chan.fileno

    def send(self, b):
        return self.chan.send(b)

    def recv(self, size):
        return self.chan.recv(size)

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<%s@%s:%s>" % \
               (self.system_user.username, self.asset.hostname, self.asset.port)


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

    def send(self, b):
        """
        If ws use proxy send data, then send the data to child sock, then
        the parent sock recv

        :param b: data
        :return:
        """
        self.child.send(b)

    def forward(self):
        while not self.stop_event.is_set():
            r, w, e = select.select([self.child], [], [])
            if self.child in r:
                data = self.child.recv(BUF_SIZE)
                if len(data) == 0:
                    self.close()
                self.ws.write_message(data)

    def auto_forward(self):
        thread = threading.Thread(target=self.forward, args=())
        thread.daemon = True
        thread.start()

    def close(self):
        self.stop_event.set()
        self.ws.close()
        self.child.close()
