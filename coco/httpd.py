#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import io
import os
import paramiko
import logging
import socket
from flask_socketio import SocketIO, Namespace, emit, join_room, leave_room
from flask import Flask, send_from_directory, render_template, request, jsonify
import uuid

# Todo: Remove for future
from jms.models import User
from .models import Request, Client, WSProxy
from .forward import ProxyServer

__version__ = '0.4.0'
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

logger = logging.getLogger(__file__)


class BaseWebSocketHandler:
    def __init__(self, *args, **kwargs):
        self.clients = dict()
        super().__init__(*args, **kwargs)

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
        return User(id='61c39c1f5b5742688180b6dda235aadd', username="admin", name="admin")

    def check_origin(self, origin):
        return True

    def close(self):
        try:
            self.clients[request.sid]["client"].close()
        except:
            pass
        pass


class SSHws(Namespace, BaseWebSocketHandler):
    def on_connect(self):
        self.clients[request.sid] = {
            "cols": int(request.cookies.get('cols', 80)),
            "rows": int(request.cookies.get('rows', 24)),
            "room": str(uuid.uuid4()),
            "chan": None,
            "proxy": None,
            "client": None,
        }
        join_room(self.clients[request.sid]["room"])

        self.prepare(request)

    def on_data(self, message):
        if self.clients[request.sid]["proxy"]:
            self.clients[request.sid]["proxy"].send({"data": message})

    def on_host(self, message):
        # 此处获取主机的信息
        print(message)
        uuid = message.get('uuid', None)
        userid = message.get('userid', None)
        if uuid and userid:
            asset = self.app.service.get_asset(uuid)
            system_user = self.app.service.get_system_user(userid)
            if system_user:
                self.socketio.start_background_task(self.clients[request.sid]["forwarder"].proxy, asset, system_user)
                # self.forwarder.proxy(self.asset, system_user)
            else:
                self.close()
        else:
            self.close()

    def on_resize(self, message):
        self.clients[request.sid]["request"].meta['width'] = message.get('cols', 80)
        self.clients[request.sid]["request"].meta['height'] = message.get('rows', 24)
        self.clients[request.sid]["request"].change_size_event.set()

    def on_disconnect(self):
        self.clients[request.sid]["proxy"].close()
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


if __name__ == "__main__":
    app = Flask(__name__, template_folder='/Users/liuzheng/gitproject/Jumpserver/webterminal/dist')


    @app.route('/luna/<path:path>')
    def send_js(path):
        return send_from_directory('/Users/liuzheng/gitproject/Jumpserver/webterminal/dist', path)


    @app.route('/')
    @app.route('/luna/')
    def index():
        return render_template('index.html')


    @app.route('/api/perms/v1/user/my/asset-groups-assets/')
    def asset_groups_assets():
        assets = [
            {
                "id": 0,
                "name": "ungrouped",
                "assets": []
            },
            {
                "id": 1,
                "name": "Default",
                "comment": "Default asset group",
                "assets": [
                    {
                        "id": 2,
                        "hostname": "192.168.1.6",
                        "ip": "192.168.2.6",
                        "port": 22,
                        "system": "windows",
                        "uuid": "xxxxxx",
                        "system_users": [
                            {
                                "id": 1,
                                "name": "web",
                                "username": "web",
                                "protocol": "ssh",
                                "auth_method": "P",
                                "auto_push": True
                            }
                        ]
                    },
                    {
                        "id": 4,
                        "hostname": "testserver123",
                        "ip": "123.57.183.135",
                        "port": 8022,
                        "system": "linux",
                        "uuid": "linux-xxlkjadf",
                        "system_users": [
                            {
                                "id": 1,
                                "name": "web",
                                "username": "web",
                                "protocol": "ssh",
                                "auth_method": "P",
                                "auto_push": True
                            }
                        ]
                    }
                ]
            },
            {
                "id": 4,
                "name": "java",
                "comment": "",
                "assets": [
                    {
                        "id": 2,
                        "hostname": "192.168.1.6",
                        "ip": "192.168.2.6",
                        "uuid": "sadcascas",
                        "system": "linux",
                        "port": 22,
                        "system_users": [
                            {
                                "id": 1,
                                "name": "web",
                                "username": "web",
                                "protocol": "ssh",
                                "auth_method": "P",
                                "auto_push": True
                            }
                        ]
                    }
                ]
            },
            {
                "id": 3,
                "name": "数据库",
                "comment": "",
                "assets": [
                    {
                        "id": 2,
                        "hostname": "192.168.1.6",
                        "ip": "192.168.2.6",
                        "port": 22,
                        "uuid": "sadcascascasdcas",
                        "system": "linux",
                        "system_users": [
                            {
                                "id": 1,
                                "name": "web",
                                "username": "web",
                                "protocol": "ssh",
                                "auth_method": "P",
                                "auto_push": True
                            }
                        ]
                    }
                ]
            },
            {
                "id": 2,
                "name": "运维组",
                "comment": "",
                "assets": [
                    {
                        "id": 2,
                        "hostname": "192.168.1.6",
                        "ip": "192.168.2.6",
                        "port": 22,
                        "uuid": "zxcasd",
                        "system": "linux",
                        "system_users": [
                            {
                                "id": 1,
                                "name": "web",
                                "username": "web",
                                "protocol": "ssh",
                                "auth_method": "P",
                                "auto_push": True
                            }
                        ]
                    }
                ]
            }
        ]
        return jsonify(assets)


    print('socketio')

    socketio = SocketIO()
    socketio.init_app(app)
    socketio.on_namespace(SSHws('/ssh'))

    socketio.run(app)
