#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
import io
import os
import paramiko
import logging
import socket
from flask_socketio import SocketIO, Namespace, emit
from flask import Flask, send_from_directory, render_template, request, jsonify

# Todo: Remove for future
from jms.models import User
from .models import Request, Client, WSProxy
from .forward import ProxyServer

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
        self.request = Request((remote_ip, 0))
        self.request.user = self.get_current_user()
        self.request.meta = {"width": self.cols, "height": self.rows}
        # self.request.__dict__.update(request.__dict__)
        self.client = Client(parent, self.request)
        self.proxy = WSProxy(self, child)
        self.app.clients.append(self.client)

    def get_current_user(self):
        return User(id='bb318c484f50483ea16589d7f18e9e95', username="admin", name="admin")

    def check_origin(self, origin):
        return True

    def close(self):
        pass


class SSHws(Namespace, BaseWebSocketHandler):
    def ssh_with_password(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect("127.0.0.1", 22, "liuzheng", "liuzheng")
        self.chan = self.ssh.invoke_shell(term='xterm', width=self.cols, height=self.rows)
        self.socketio.start_background_task(self.send_data)
        # self.chan.settimeout(0.1)

    def send_data(self):
        while True:
            data = self.chan.recv(2048).decode('utf-8', 'replace')
            self.emit('data', data)

    def on_connect(self):
        self.cols = int(request.cookies.get('cols', 80))
        self.rows = int(request.cookies.get('rows', 24))
        self.prepare(request)
        self.forwarder = ProxyServer(self.app, self.client)

        # InteractiveServer(self.app, self.client).interact_async()

    def on_data(self, message):
        # self.chan.send(message)
        # while not self.chan.recv_ready():
        self.proxy.send({"data": message})
        # emit('data', self.chan.recv(2048).decode('utf-8', 'replace'))

    # def on_event(self, message):
    #     self.evt_handle(message)

    def on_host(self, message):
        # 此处获取主机的信息
        print(message)
        uuid = message.get('uuid', None)
        username = message.get('username', None)
        system_user = None

        if uuid and username:
            self.asset = self.app.service.get_asset(uuid)
            for i in self.asset.system_users_granted:
                if i.username == username:
                    system_user = username
            if system_user:
                self.forwarder.proxy(self.asset, system_user)

    def on_resize(self, message):
        self.request.meta['width'] = message.get('cols', 80)
        self.request.meta['height'] = message.get('rows', 24)
        self.request.change_size_event.set()

    def on_disconnect(self):
        self.proxy.close()
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
