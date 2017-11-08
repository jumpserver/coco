# coding: utf-8
import socket
import json
import logging

import tornado.web
import tornado.websocket
import tornado.httpclient
import tornado.ioloop
import tornado.gen

# Todo: Remove for future
from jms.models import User
from .models import Request, Client, WSProxy
from .interactive import InteractiveServer


logger = logging.getLogger(__file__)


class BaseWehSocketHandler:
    def prepare(self):
        self.app = self.settings["app"]
        child, parent = socket.socketpair()
        request = Request((self.request.remote_ip, 0))
        request.user = self.current_user
        self.request.__dict__.update(request.__dict__)
        self.client = Client(parent, self.request)
        self.proxy = WSProxy(self, child)
        self.app.clients.append(self.client)

    def get_current_user(self):
        return User(id=1, username="guanghongwei", name="广宏伟")

    def check_origin(self, origin):
        return True


class InteractiveWehSocketHandler(BaseWehSocketHandler, tornado.websocket.WebSocketHandler):
    @tornado.web.authenticated
    def open(self):
        InteractiveServer(self.app, self.client).activate_async()

    def on_message(self, message):
        try:
            message = json.loads(message)
        except json.JSONDecodeError:
            logger.info("Loads websocket json message failed")
            return

        if message.get('event'):
            self.evt_handle(message)
        elif message.get('data'):
            self.proxy.send(message)

    def on_close(self):
        self.proxy.close()

    def evt_handle(self, data):
        if data['event'] == 'change_size':
            try:
                self.request.meta['width'] = data['meta']['width']
                self.request.meta['height'] = data['meta']['height']
                self.request.change_size_event.set()
            except KeyError:
                pass


class ProxyWehSocketHandler(BaseWehSocketHandler):
    pass


class MonitorWehSocketHandler(BaseWehSocketHandler):
    pass


class HttpServer:
    routers = [
        (r'/ws/interactive/', InteractiveWehSocketHandler),
        (r'/ws/proxy/(?P<asset_id>[0-9]+)/(?P<system_user_id>[0-9]+)/', ProxyWehSocketHandler),
        (r'/ws/session/(?P<session_id>[0-9]+)/monitor/', MonitorWehSocketHandler),
    ]

    # prepare may be rewrite it
    settings = {
        'cookie_secret': '',
        'app': None,
        'login_url': '/login'
    }

    def __init__(self, app):
        self.app = app
        self._prepare()

    def _prepare(self):
        self.settings['cookie_secret'] = self.app.config['SECRET_KEY']
        self.settings['app'] = self.app

    def run(self):
        host = self.app.config["BIND_HOST"]
        port = self.app.config["WS_PORT"]
        print('Starting websocket server at %(host)s:%(port)s' %
              {"host": host, "port": port})
        ws = tornado.web.Application(self.routers, **self.settings)
        ws.listen(port=port, address=host)
        tornado.ioloop.IOLoop.current().start()
