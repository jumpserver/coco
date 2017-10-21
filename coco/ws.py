# coding: utf-8

import tornado.web
import tornado.websocket
import tornado.httpclient
import tornado.ioloop


class MainHandler(tornado.web.RequestHandler):
    def get(self, *args, **kwargs):
        self.write("Hello world")


class InteractiveHandler(tornado.websocket.WebSocketHandler):
    pass


class ProxyHandler(tornado.websocket.WebSocketHandler):
    pass


class MonitorHandler(tornado.websocket.WebSocketHandler):
    pass


class WSServer:
    routers = [
        (r'^/$', MainHandler),
        (r'/ws/interactive/', MainHandler),
        (r'/ws/proxy/(?P<asset_id>[0-9]+)/(?P<system_user_id>[0-9]+)/', MainHandler),
        (r'/ws/session/(?P<session_id>[0-9]+)/monitor/', MainHandler),
        (r'/ws/session/(?P<session+id>[0-9]+)/join/', MainHandler),
    ]

    def __init__(self, app):
        self.app = app

    def run(self):
        host = self.app.config["BIND_HOST"]
        port = self.app.config["WS_PORT"]
        print('Starting websocket server at %(host)s:%(port)s' %
              {"host": host, "port": port})
        ws = tornado.web.Application(self.routers)
        ws.listen(port=port, address=host)
        tornado.ioloop.IOLoop.current().start()
