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
        if self.current_user is None:
            return redirect(current_app.config['LOGIN_URL'])
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

    def new_connection(self):
        self.connections[request.sid] = dict()

    def new_room(self):
        room_id = str(uuid.uuid4())
        room = {
            "id": room_id,
            "proxy": None,
            "client": None,
            "forwarder": None,
            "request": self.make_coco_request(),
            "cols": 80,
            "rows": 24
        }
        self.connections[request.sid][room_id] = room
        return room

    @staticmethod
    def get_win_size():
        cols_request = request.cookies.get('cols')
        rows_request = request.cookies.get('rows')
        if cols_request and cols_request.isdigit():
            cols = int(cols_request)
        else:
            cols = 80

        if rows_request and rows_request.isdigit():
            rows = int(rows_request)
        else:
            rows = 24
        return cols, rows

    def make_coco_request(self):
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr

        width, height = self.get_win_size()
        req = Request((remote_ip, 0))
        req.user = self.current_user
        req.meta = {
            "width": width,
            "height": height,
        }
        return req

    def on_connect(self):
        logger.debug("On connect event trigger")
        super().on_connect()
        self.new_connection()

    def on_host(self, message):
        # 此处获取主机的信息
        logger.debug("On host event trigger")
        asset_id = message.get('uuid', None)
        user_id = message.get('userid', None)
        secret = message.get('secret', None)
        room = self.new_room()

        self.emit('room', {'room': room["id"], 'secret': secret})
        join_room(room["id"])
        if not asset_id or not user_id:
            # self.on_connect()
            return

        asset = app_service.get_asset(asset_id)
        system_user = app_service.get_system_user(user_id)

        if not asset or not system_user:
            self.on_connect()
            return

        child, parent = socket.socketpair()
        client = Client(parent, room["request"])
        forwarder = ProxyServer(client)
        room["client"] = client
        room["forwarder"] = forwarder
        room["proxy"] = WSProxy(self, child, room["id"])
        room["cols"], room["rows"] = self.get_win_size()
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
        secret = message.get('secret', None)
        room = self.new_room()
        self.emit('room', {'room': room["id"], 'secret': secret})
        if not token or not secret:
            logger.debug("Token or secret is None")
            self.emit('data', {'data': "\nOperation not permitted!",
                               'room': room["id"]})
            self.emit('disconnect')
            return None

        info = app_service.get_token_asset(token)
        logger.debug(info)
        if not info:
            logger.debug("Token info is None")
            self.emit('data', {'data': "\nOperation not permitted!",
                               'room': room["id"]})
            self.emit('disconnect')
            return None

        user_id = info.get('user', None)
        self.current_user = app_service.get_user_profile(user_id)
        room["request"].user = self.current_user
        logger.debug(self.current_user)
        self.on_host({
            'secret': secret,
            'uuid': info['asset'],
            'userid': info['system_user'],
        })

    def on_resize(self, message):
        cols, rows = message.get('cols', None), message.get('rows', None)
        logger.debug("On resize event trigger: {}*{}".format(cols, rows))
        rooms = self.connections.get(request.sid)
        if not rooms:
            return
        room = list(rooms.values())[0]
        if rooms and (room["cols"], room["rows"]) != (cols, rows):
            for room in rooms.values():
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
            room["proxy"].close()
            self.close_room(room_id)
            del self.connections[request.sid][room_id]
            del room


class HttpServer:
    # prepare may be rewrite it
    config = {
        'SECRET_KEY': 'someWOrkSD20KMS9330)&#',
        'coco': None,
        'LOGIN_URL': '/login'
    }
    init_kwargs = dict(
        # async_mode="gevent",
        async_mode="threading",
        ping_timeout=20,
        ping_interval=10
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
        self.socket_io.init_app(
            self.flask_app,
            **self.init_kwargs
        )
        self.socket_io.run(self.flask_app, port=port, host=host, debug=False)

    def shutdown(self):
        self.socket_io.server.close()
