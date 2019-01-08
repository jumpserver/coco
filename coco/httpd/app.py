# -*- coding: utf-8 -*-
#

import os
from flask_socketio import SocketIO
from flask import Flask

from coco.utils import get_logger
from coco.conf import config
from coco.httpd.ws import ProxyNamespace, ElfinderNamespace

logger = get_logger(__file__)

app = Flask(__name__, template_folder='templates',
            static_folder='static')
app.config.update(config)
socket_io = SocketIO()
socket_io.on_namespace(ProxyNamespace('/ssh'))
socket_io.on_namespace(ElfinderNamespace('/elfinder'))

if os.environ.get('USE_EVENTLET', '1') == '1':
    init_kwargs = {'async_mode': 'eventlet'}
else:
    init_kwargs = {'async_mode': 'threading'}
socket_io.init_app(app, **init_kwargs),
socket_io.on_error_default(lambda x: logger.exception(x))


class HttpServer:
    @staticmethod
    def run():
        host = config["BIND_HOST"]
        port = config["HTTPD_PORT"]
        print('Starting websocket server at {}:{}'.format(host, port))
        socket_io.run(app, port=port, host=host, debug=False)

    @staticmethod
    def shutdown():
        socket_io.stop()
        pass



