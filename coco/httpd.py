#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import os
import socket
import uuid
from flask_socketio import SocketIO, Namespace, join_room, leave_room
from flask import Flask, request, current_app, redirect

from .models import Request, Client, WSProxy
from .proxy import ProxyServer
from .utils import get_logger

__version__ = '0.5.0'
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

logger = get_logger(__file__)


class BaseNamespace(Namespace):
    clients = None
    current_user = None

    @property
    def app(self):
        app = current_app.config['coco']
        return app

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
            user = self.app.service.check_user_cookie(session_id, csrf_token)
        if token:
            user = self.app.service.check_user_with_token(token)
        return user

    def close(self):
        try:
            self.clients[request.sid]["client"].close()
        except IndexError:
            pass


class ProxyNamespace(BaseNamespace):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connections = dict()
        self.rooms = dict()

    def new_connection(self):
        room_id = str(uuid.uuid4())
        connection = {
            "cols": int(request.cookies.get('cols', 80)),
            "rows": int(request.cookies.get('rows', 24)),
            "room": room_id,
            "proxy": dict(),
            "client": dict(),
            "forwarder": dict(),
            "request": self.make_coco_request()
        }
        return connection

    def make_coco_request(self):
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr

        width_request = request.cookies.get('cols')
        rows_request = request.cookies.get('rows')
        if width_request and width_request.isdigit():
            width = int(width_request)
        else:
            width = 80

        if rows_request and rows_request.isdigit():
            rows = int(rows_request)
        else:
            rows = 24
        req = Request((remote_ip, 0))
        req.user = self.current_user
        req.meta = {
            "width": width,
            "height": rows,
        }
        return req

    def on_connect(self):
        logger.debug("On connect event trigger")
        super().on_connect()
        connection = self.new_connection()
        self.connections[request.sid] = connection
        self.rooms[connection['room']] = {
            "admin": request.sid,
            "member": [],
            "rw": []
        }
        join_room(connection['room'])

    def on_host(self, message):
        # 此处获取主机的信息
        logger.debug("On host event trigger")
        room_id = str(uuid.uuid4())
        asset_id = message.get('uuid', None)
        user_id = message.get('userid', None)
        secret = message.get('secret', None)

        self.emit('room', {'room': room_id, 'secret': secret})
        if not asset_id or not user_id:
            # self.on_connect()
            return

        asset = self.app.service.get_asset(asset_id)
        system_user = self.app.service.get_system_user(user_id)

        if not asset or not system_user:
            self.on_connect()
            return

        child, parent = socket.socketpair()
        self.connections[request.sid]["client"][room_id] = Client(
            parent, self.connections[request.sid]["request"]
        )
        self.connections[request.sid]["proxy"][room_id] = WSProxy(
            self, child, self.connections[request.sid]["room"], room_id
        )
        self.connections[request.sid]["forwarder"][room_id] = ProxyServer(
            self.app, self.connections[request.sid]["client"][room_id]
        )
        self.socketio.start_background_task(
            self.connections[request.sid]["forwarder"][room_id].proxy,
            asset, system_user
        )

    def on_data(self, message):
        """
        收到浏览器请求
        :param message: {"data": "xxx", "room": "xxx"}
        :return:
        """
        room = message.get('room')
        if not room:
            return
        room_proxy = self.connections[request.sid]['proxy'].get(room)
        if room_proxy:
            room_proxy.send({"data": message['data']})

    def on_token(self, message):
        # 此处获取token含有的主机的信息
        logger.debug("On token trigger")
        token = message.get('token', None)
        secret = message.get('secret', None)
        connection = str(uuid.uuid4())
        self.emit('room', {'room': connection, 'secret': secret})
        if not (token or secret):
            logger.debug("token or secret is None")
            self.emit('data', {'data': "\nOperation not permitted!", 'room': connection})
            self.emit('disconnect')
            return None

        info = self.app.service.get_token_asset(token)
        logger.debug(info)
        if not info:
            logger.debug("host is None")
            self.emit('data', {'data': "\nOperation not permitted!", 'room': connection})
            self.emit('disconnect')
            return None

        user_id = info.get('user', None)
        logger.debug("self.current_user")
        self.current_user = self.app.service.get_user_profile(user_id)
        self.connections[request.sid]["request"].user = self.current_user
        logger.debug(self.current_user)
        self.on_host({'secret': secret, 'uuid': info['asset'], 'userid': info['system_user']})

    def on_resize(self, message):
        cols = message.get('cols')
        rows = message.get('rows')
        logger.debug("On resize event trigger: {}*{}".format(cols, rows))
        if cols and rows and self.connections[request.sid]["request"]:
            self.connections[request.sid]["request"].meta['width'] = cols
            self.connections[request.sid]["request"].meta['height'] = rows
            self.connections[request.sid]["request"].change_size_event.set()

    # def on_room(self, session_id):
    #     logger.debug("On room event trigger")
    #     if session_id not in self.connections.keys():
    #         self.emit(
    #             'error', "no such session",
    #             room=self.connections[request.sid]["room"]
    #         )
    #     else:
    #         self.emit(
    #             'room', self.connections[session_id]["room"],
    #             room=self.connections[request.sid]["room"]
    #         )
    #
    # def on_join(self, room):
    #     logger.debug("On join room event trigger")
    #     self.on_leave(self.connections[request.id]["room"])
    #     self.connections[request.sid]["room"] = room
    #     self.rooms[room]["member"].append(request.sid)
    #     join_room(room=room)
    #
    def on_leave(self, room):
        logger.debug("On leave room event trigger")
        if self.rooms[room]["admin"] == request.sid:
            self.emit("data", "\nAdmin leave", room=room)
            del self.rooms[room]
        leave_room(room=room)

    def on_disconnect(self):
        logger.debug("On disconnect event trigger")
        # self.on_leave(self.clients[request.sid]["room"])
        print(self.connections[request.sid]["client"])
        try:
            for connection in self.connections[request.sid]["client"]:
                self.on_logout(connection)
            del self.connections[request.sid]
        except IndexError:
            pass

    def on_logout(self, connection):
        logger.debug("On logout event trigger")
        if connection in self.connections[request.sid]["proxy"].keys():
            self.connections[request.sid]["proxy"][connection].close()
            del self.connections[request.sid]['proxy'][connection]


class HttpServer:
    # prepare may be rewrite it
    config = {
        'SECRET_KEY': '',
        'coco': None,
        'LOGIN_URL': '/login'
    }
    init_kwargs = dict(
        async_mode="threading",
        ping_timeout=20,
        ping_interval=10
    )

    def __init__(self, coco):
        config = coco.config
        config.update(self.config)
        config['coco'] = coco
        self.flask_app = Flask(__name__, template_folder='dist')
        self.flask_app.config.update(config)
        self.socket_io = SocketIO()
        self.register_routes()

    def register_routes(self):
        self.socket_io.on_namespace(ProxyNamespace('/ssh'))

    def run(self):
        host = self.flask_app.config["BIND_HOST"]
        port = self.flask_app.config["HTTPD_PORT"]
        self.socket_io.init_app(
            self.flask_app,
            **self.init_kwargs
        )
        self.socket_io.run(self.flask_app, port=port, host=host, debug=False)

    def shutdown(self):
        pass
