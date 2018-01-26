#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import os
import socket
from flask_socketio import SocketIO, Namespace, emit, join_room, leave_room
from flask import Flask, send_from_directory, render_template, request, jsonify
import uuid

# Todo: Remove for future
from jms.models import User
from .models import Request, Client, WSProxy
from .proxy import ProxyServer
from .utils import get_logger

__version__ = '0.4.0'
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

logger = get_logger(__file__)


class BaseWebSocketHandler:
    clients = None
    current_user = None

    def app(self, app):
        self.app = app
        return self

    def prepare(self, request):
        # self.app = self.settings["app"]
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr
        req = Request((remote_ip, 0))
        req.user = self.current_user
        req.meta = {
            "width": self.clients[request.sid]["cols"],
            "height": self.clients[request.sid]["rows"]
        }
        self.clients[request.sid]["request"] = req

    def check_origin(self, origin):
        return True

    def close(self):
        try:
            self.clients[request.sid]["client"].close()
        except:
            pass


class SSHws(Namespace, BaseWebSocketHandler):
    def __init__(self, *args, **kwargs):
        self.clients = dict()
        self.rooms = dict()
        super().__init__(*args, **kwargs)

    def on_connect(self):
        room = str(uuid.uuid4())
        self.clients[request.sid] = {
            "cols": int(request.cookies.get('cols', 80)),
            "rows": int(request.cookies.get('rows', 24)),
            "room": room,
            # "chan": dict(),
            "proxy": dict(),
            "client": dict(),
            "forwarder": dict(),
            "request": None,
        }
        self.rooms[room] = {
            "admin": request.sid,
            "member": [],
            "rw": []
        }
        join_room(room)
        self.current_user = self.app.service.check_user_cookie(
            session_id=request.cookies.get('sessionid', ''),
            csrf_token=request.cookies.get('csrftoken', '')
        )
        self.prepare(request)

    def on_data(self, message):
        if message['room'] and self.clients[request.sid]["proxy"][message['room']]:
            self.clients[request.sid]["proxy"][message['room']].send({"data": message['data']})

    def on_host(self, message):
        # 此处获取主机的信息
        connection = str(uuid.uuid4())
        asset_id = message.get('uuid', None)
        user_id = message.get('userid', None)
        self.emit('room', {'room': connection, 'secret': message['secret']})

        if asset_id and user_id:
            asset = self.app.service.get_asset(asset_id)
            system_user = self.app.service.get_system_user(user_id)

            if system_user:
                child, parent = socket.socketpair()
                self.clients[request.sid]["client"][connection] = Client(
                    parent, self.clients[request.sid]["request"]
                )
                self.clients[request.sid]["proxy"][connection] = WSProxy(
                    self, child, self.clients[request.sid]["room"], connection
                )
                self.clients[request.sid]["forwarder"][
                    connection] = ProxyServer(
                    self.app, self.clients[request.sid]["client"][connection]
                )
                self.app.clients.append(self.clients[request.sid]["client"][connection])
                self.socketio.start_background_task(
                    self.clients[request.sid]["forwarder"][connection].proxy,
                    asset, system_user
                )
                # self.forwarder.proxy(self.asset, system_user)
            else:
                self.on_disconnect()
        else:
            self.on_disconnect()

    def on_resize(self, message):
        if self.clients[request.sid]["request"]:
            self.clients[request.sid]["request"].meta['width'] = message.get('cols', 80)
            self.clients[request.sid]["request"].meta['height'] = message.get('rows', 24)
            self.clients[request.sid]["request"].change_size_event.set()

    def on_room(self, sessionid):
        if sessionid not in self.clients.keys():
            self.emit('error', "no such session", room=self.clients[request.sid]["room"])
        else:
            self.emit('room', self.clients[sessionid]["room"], room=self.clients[request.sid]["room"])

    def on_join(self, room):
        self.on_leave(self.clients[request.id]["room"])
        self.clients[request.sid]["room"] = room
        self.rooms[room]["member"].append(request.sid)
        join_room(room=room)

    def on_leave(self, room):
        if self.rooms[room]["admin"] == request.sid:
            self.emit("data", "\nAdmin leave", room=room)
            del self.rooms[room]
        leave_room(room=room)

    def on_disconnect(self):
        self.on_leave(self.clients[request.sid]["room"])
        try:
            for connection in self.clients[request.sid]["client"]:
                self.on_logout(connection)
            del self.clients[request.sid]
        except:
            pass

    def on_logout(self, connection):
        if connection:
            if connection in self.clients[request.sid]["proxy"].keys():
                self.clients[request.sid]["proxy"][connection].close()

    def logout(self, connection):
        if connection and (request.sid in self.clients.keys()):
            if connection in self.clients[request.sid]["proxy"].keys():
                del self.clients[request.sid]["proxy"][connection]
            if connection in self.clients[request.sid]["forwarder"].keys():
                del self.clients[request.sid]["forwarder"][connection]
            if connection in self.clients[request.sid]["client"].keys():
                del self.clients[request.sid]["client"][connection]


class HttpServer:
    # prepare may be rewrite it
    settings = {
        'cookie_secret': '',
        'app': None,
        'login_url': '/login'
    }

    def __init__(self, app):
        self.app = app
        # self.settings['cookie_secret'] = self.app.config['SECRET_KEY']
        # self.settings['app'] = self.app

        self.flask = Flask(__name__, template_folder='dist')
        self.flask.config['SECRET_KEY'] = self.app.config['SECRET_KEY']
        self.socketio = SocketIO()

    def run(self):
        host = self.app.config["BIND_HOST"]
        port = self.app.config["HTTPD_PORT"]
        print('Starting websocket server at {}:{}'.format(host, port))
        self.socketio.on_namespace(SSHws('/ssh').app(self.app))
        self.socketio.init_app(self.flask, async_mode="threading")
        self.socketio.run(self.flask, port=port, host=host)

    def shutdown(self):
        pass
