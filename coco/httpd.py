#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import os
import socket
import uuid
from flask_socketio import SocketIO, Namespace, join_room
from flask import Flask, request, current_app, redirect

from .models import Request, Client, WSProxy
from .proxy import ProxyServer
from .utils import get_logger
from .ctx import current_app, app_service

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = get_logger(__file__)


class BaseNamespace(Namespace):
    current_user = None

    def on_connect(self):
        self.current_user = self.get_current_user()
        logger.debug("{} connect websocket".format(self.current_user))

    def get_current_user(self):
        session_id = request.cookies.get('sessionid', '')
        csrf_token = request.cookies.get('csrftoken', '')
        token = request.headers.get("Authorization")
        user = None
        if session_id and csrf_token:
            user = app_service.check_user_cookie(session_id, csrf_token)
        if token:
            user = app_service.check_user_with_token(token)
        msg = "Get current user: session_id<{}> token<{}> => {}".format(
            session_id, token, user
        )
        logger.debug(msg)
        return user


class ProxyNamespace(BaseNamespace):
    def __init__(self, *args, **kwargs):
        """
        :param args:
        :param kwargs:

        self.connections = {
            "request_sid": {
                "room_id": {
                    "id": room_id,
                    "proxy": None,
                    "client": None,
                    "forwarder": None,
                    "request": None,
                    "cols": 80,
                    "rows": 24
                },

                ...
            },
            ...
        }
        """
        super().__init__(*args, **kwargs)
        self.connections = dict()
        self.win_size = None

    def new_connection(self):
        self.connections[request.sid] = dict()

    def new_room(self, current_user, cols=80, rows=24):
        room_id = str(uuid.uuid4())
        req = self.make_coco_request(current_user, cols=cols, rows=rows)
        room = {
            "id": room_id,
            "proxy": None,
            "client": None,
            "forwarder": None,
            "request": req,
            "cols": cols,
            "rows": rows
        }
        self.connections[request.sid][room_id] = room
        return room

    @staticmethod
    def make_coco_request(user, cols=80, rows=24):
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr

        req = Request((remote_ip, 0))
        req.user = user
        req.meta = {"width": cols, "height": rows}
        return req

    def on_connect(self):
        logger.debug("On connect event trigger")
        super().on_connect()
        self.new_connection()

    def on_host(self, message):
        # 此处获取主机的信息
        logger.debug("On host event trigger")
        current_user = self.get_current_user()
        self.connect_host(current_user, message)

    def connect_host(self, current_user, message):
        asset_id = message.get('uuid', None)
        system_user_id = message.get('userid', None)
        secret = message.get('secret', None)
        cols, rows = message.get('size', (80, 24))
        room = self.new_room(current_user, cols=cols, rows=rows)

        self.emit('room', {'room': room["id"], 'secret': secret})
        join_room(room["id"])
        if not asset_id or not system_user_id:
            return

        asset = app_service.get_asset(asset_id)
        system_user = app_service.get_system_user(system_user_id)

        if not asset or not system_user:
            return

        child, parent = socket.socketpair()
        client = Client(parent, room["request"])
        forwarder = ProxyServer(client, login_from='WT')
        room["client"] = client
        room["forwarder"] = forwarder
        room["proxy"] = WSProxy(self, child, room["id"])
        self.socketio.start_background_task(
            forwarder.proxy, asset, system_user
        )

    def on_data(self, message):
        """
        收到浏览器请求
        :param message: {"data": "xxx", "room": "xxx"}
        :return:
        """
        room_id = message.get('room')
        room = self.connections.get(request.sid, {}).get(room_id)
        if not room:
            return
        room["proxy"].send({"data": message['data']})

    def on_token(self, message):
        # 此处获取token含有的主机的信息
        logger.debug("On token trigger")
        token = message.get('token', None)
        secret = message.get("secret", None)
        win_size = message.get('size', (80, 24))

        room = self.new_room(None)
        self.emit('room', {'room': room["id"], 'secret': secret})
        join_room(room['id'])

        if not token or not secret:
            msg = "Token or secret is None: {} {}".format(token, secret)
            logger.error(msg)
            self.emit('data',  {'data': msg, 'room': room['id']}, room=room['id'])
            self.emit('disconnect')
            return

        info = app_service.get_token_asset(token)
        logger.debug(info)
        if not info:
            msg = "Token info is none, maybe token expired"
            logger.error(msg)
            self.emit('data',  {'data': msg, 'room': room['id']}, room=room['id'])
            self.emit('disconnect')
            return None

        user_id = info.get('user', None)
        current_user = app_service.get_user_profile(user_id)
        message = {
            'secret': secret,
            'uuid': info['asset'],
            'userid': info['system_user'],
            'size': win_size,
        }
        self.connect_host(current_user, message)

    def on_resize(self, message):
        cols, rows = message.get('cols', None), message.get('rows', None)
        logger.debug("On resize event trigger: {}*{}".format(cols, rows))
        rooms = self.connections.get(request.sid, {})
        logger.debug("Start change win size: {}*{}".format(cols, rows))
        for room in rooms.values():
            if (room["cols"], room["rows"]) == (cols, rows):
                continue
            room["request"].meta.update({
                'width': cols, 'height': rows
            })
            room["request"].change_size_event.set()
            room.update({"cols": cols, "rows": rows})

    def on_disconnect(self):
        logger.debug("On disconnect event trigger")
        rooms = {k: v for k, v in self.connections.get(request.sid, {}).items()}
        for room_id in rooms:
            try:
                self.on_logout(room_id)
            except Exception as e:
                logger.warn(e)
        del self.connections[request.sid]

    def on_logout(self, room_id):
        room = self.connections.get(request.sid, {}).get(room_id)
        if room:
            room.get("proxy") and room["proxy"].close()
            self.close_room(room_id)
            del self.connections[request.sid][room_id]
            del room

    def on_ping(self):
        self.emit('pong')


class HttpServer:
    # prepare may be rewrite it
    config = {
        'SECRET_KEY': 'someWOrkSD20KMS9330)&#',
        'coco': None,
        'LOGIN_URL': '/login'
    }
    init_kwargs = dict(
        async_mode="eventlet",
        # async_mode="threading",
        # ping_timeout=20,
        # ping_interval=10,
        # engineio_logger=True,
        # logger=True
    )

    def __init__(self):
        config = {k: v for k, v in current_app.config.items()}
        config.update(self.config)
        self.flask_app = Flask(__name__, template_folder='dist')
        self.flask_app.config.update(config)
        self.socket_io = SocketIO()
        self.register_routes()
        self.register_error_handler()

    def register_routes(self):
        self.socket_io.on_namespace(ProxyNamespace('/ssh'))

    @staticmethod
    def on_error_default(e):
        logger.exception(e)

    def register_error_handler(self):
        self.socket_io.on_error_default(self.on_error_default)

    def run(self):
        host = self.flask_app.config["BIND_HOST"]
        port = self.flask_app.config["HTTPD_PORT"]
        print('Starting websocket server at {}:{}'.format(host, port))
        self.socket_io.init_app(
            self.flask_app,
            **self.init_kwargs
        )
        self.socket_io.run(self.flask_app, port=port, host=host, debug=False)

    def shutdown(self):
        self.socket_io.stop()
        pass
