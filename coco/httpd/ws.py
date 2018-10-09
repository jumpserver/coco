# -*- coding: utf-8 -*-
#

import os
import uuid
from flask_socketio import join_room
from flask import request

from ..models import Connection, WSProxy
from ..proxy import ProxyServer
from ..utils import get_logger
from ..ctx import app_service
from .base import BaseNamespace
from .utils import get_cached_volume

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = get_logger(__file__)


class ProxyNamespace(BaseNamespace):
    def __init__(self, *args, **kwargs):
        """
        :param args:
        :param kwargs:

        self.connections = {
            "request_sid": connection,
            ...
        }
        """
        super().__init__(*args, **kwargs)
        self.win_size = None

    def new_connection(self):
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr
        connection = Connection.new_connection(
            addr=(remote_ip, 0), cid=request.sid, sock=self
        )
        connection.user = request.current_user
        connection.login_from = 'WT'

    def on_connect(self):
        logger.debug("On connect event trigger")
        self.get_current_user()
        super().on_connect()
        self.new_connection()

    def on_host(self, message):
        # 此处获取主机的信息
        logger.debug("On host event trigger")
        self.connect_host(message)

    def connect_host(self, message):
        asset_id = message.get('uuid', None)
        system_user_id = message.get('userid', None)
        secret = message.get('secret', None)
        cols, rows = message.get('size', (80, 24))

        connection = Connection.get_connection(request.sid)
        client_id = str(uuid.uuid4())
        client = connection.new_client(client_id)
        client.request.kind = 'session'
        client.request.type = 'pty'
        client.request.meta.update({
            'pty': b'xterm', 'width': cols, 'height': rows,
        })
        ws_proxy = WSProxy(self, client_id)
        client.chan = ws_proxy
        self.emit('room', {'room': client_id, 'secret': secret})
        join_room(client_id)
        if not asset_id or not system_user_id:
            return

        asset = app_service.get_asset(asset_id)
        system_user = app_service.get_system_user(system_user_id)

        if not asset or not system_user:
            return
        forwarder = ProxyServer(client, asset, system_user)

        def proxy():
            try:
                forwarder.proxy()
            except Exception as e:
                logger.error("Unexpected error occur: {}".format(e))
            self.logout(client_id, connection)
        self.socketio.start_background_task(proxy)

    def on_data(self, message):
        """
        收到浏览器请求
        :param message: {"data": "xxx", "room": "xxx"}
        :return:
        """
        client_id = message.get('room')
        connection = Connection.get_connection(request.sid)
        if not connection:
            return
        client = connection.clients.get(client_id)
        if not client:
            return
        client.chan.write(message.get("data", ""))

    def check_token(self, token, secret, client_id):
        if not token and not secret:
            msg = "Token or secret is None: {} {}".format(token, secret)
            logger.error(msg)
            self.emit('data', {'data': msg, 'room': client_id}, room=client_id)
            self.emit('disconnect')
            return False, None

        info = app_service.get_token_asset(token)
        logger.debug(info)
        if not info:
            msg = "Token info is none, maybe token expired"
            logger.error(msg)
            self.emit('data', {'data': msg, 'room': client_id}, room=client_id)
            self.emit('disconnect')
            return False, None
        return True, info

    def on_token(self, message):
        # 此处获取token含有的主机的信息
        logger.debug("On token trigger")
        token = message.get('token', None)
        secret = message.get("secret", None)
        win_size = message.get('size', (80, 24))

        client_id = str(uuid.uuid4())
        self.emit('room', {'room': client_id, 'secret': secret})
        join_room(client_id)
        valid, info = self.check_token(token, secret, client_id)
        if not valid:
            return
        user_id = info.get('user', None)

        request.current_user = current_user = app_service.get_user_profile(user_id)
        connection = Connection.get_connection(request.sid)
        connection.user = current_user
        message = {
            'secret': secret,
            'uuid': info['asset'],
            'userid': info['system_user'],
            'size': win_size,
        }
        self.connect_host(message)

    def on_resize(self, message):
        cols, rows = message.get('cols', None), message.get('rows', None)
        logger.debug("On resize event trigger: {}*{}".format(cols, rows))
        connection = Connection.get_connection(request.sid)
        if not connection:
            logger.error("Not connection found")
            return
        logger.debug("Start change win size: {}*{}".format(cols, rows))
        for client in connection.clients.values():
            if (client.request.meta["width"], client.request.meta["height"]) == (cols, rows):
                continue
            client.request.meta.update({
                'width': cols, 'height': rows
            })
            client.change_size_evt.set()

    def on_disconnect(self):
        logger.debug("On disconnect event trigger")
        connection = Connection.get_connection(request.sid)
        if not connection:
            return
        clients_copy = list(connection.clients.keys())
        for client_id in clients_copy:
            try:
                self.on_logout(client_id)
            except Exception as e:
                logger.warn(e)
        Connection.remove_connection(connection.id)

    def logout(self, client_id, connection):
        connection.remove_client(client_id)
        self.emit('logout', {"room": client_id}, room=client_id)

    def on_logout(self, client_id):
        logger.debug("On logout event trigger: {}".format(client_id))
        connection = Connection.get_connection(request.sid)
        if not connection:
            return
        self.logout(client_id, connection)

    def close(self):
        pass

    def on_ping(self):
        self.emit('pong')


class ElfinderNamespace(BaseNamespace):
    def on_connect(self):
        self.emit('data', {"sid": str(request.sid)})

    def on_disconnect(self):
        sftp = get_cached_volume(request.sid)
        if sftp:
            sftp.close()
