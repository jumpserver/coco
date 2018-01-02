#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import os
import logging
import socket
from flask_socketio import SocketIO, Namespace, emit, join_room, leave_room
from flask import Flask, send_from_directory, render_template, request, jsonify
import uuid

# Todo: Remove for future
from jms.models import User
from .models import Request, Client, WSProxy
from .proxy import ProxyServer

__version__ = '0.4.0'
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

logger = logging.getLogger(__file__)


class BaseWebSocketHandler:
    def app(self, app):
        self.app = app
        return self

    def prepare(self, request):
        # self.app = self.settings["app"]
        child, parent = socket.socketpair()
        if request.headers.getlist("X-Forwarded-For"):
            remote_ip = request.headers.getlist("X-Forwarded-For")[0]
        else:
            remote_ip = request.remote_addr
        self.clients[request.sid]["request"] = Request((remote_ip, 0))
        self.clients[request.sid]["request"].user = self.get_current_user()
        self.clients[request.sid]["request"].meta = {"width": self.clients[request.sid]["cols"],
                                                     "height": self.clients[request.sid]["rows"]}
        # self.request.__dict__.update(request.__dict__)
        self.clients[request.sid]["client"] = Client(parent, self.clients[request.sid]["request"])
        self.clients[request.sid]["proxy"] = WSProxy(self, child, self.clients[request.sid]["room"])
        self.app.clients.append(self.clients[request.sid]["client"])
        self.clients[request.sid]["forwarder"] = ProxyServer(self.app, self.clients[request.sid]["client"])

    def get_current_user(self):
        return self.app.service.get_profile()

    def check_origin(self, origin):
        return True

    def close(self):
        try:
            self.clients[request.sid]["client"].close()
        except:
            pass
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
            "chan": None,
            "proxy": None,
            "client": None,
            "request": None,
        }
        self.rooms[room] = {
            "admin": request.sid,
            "member": [],
            "rw": []
        }
        join_room(room)

        self.prepare(request)

    def on_data(self, message):
        if self.clients[request.sid]["proxy"]:
            self.clients[request.sid]["proxy"].send({"data": message})

    def on_host(self, message):
        # 此处获取主机的信息
        uuid = message.get('uuid', None)
        userid = message.get('userid', None)
        if uuid and userid:
            asset = self.app.service.get_asset(uuid)
            system_user = self.app.service.get_system_user(userid)
            if system_user:
                self.socketio.start_background_task(self.clients[request.sid]["forwarder"].proxy, asset, system_user)
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
            # todo: there maybe have bug
            self.clients[request.sid]["proxy"].close()
        except:
            pass
        # self.ssh.close()
        pass


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
        self.socketio.init_app(self.flask)
        self.socketio.run(self.flask, port=port, host=host)

    def shutdown(self):
        pass

