#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import threading
import time

from paramiko.ssh_exception import SSHException

from .session import Session
from .models import Server, TelnetServer
from .connection import SSHConnection, TelnetConnection
from .ctx import current_app, app_service
from .utils import wrap_with_line_feed as wr, wrap_with_warning as warning, \
     get_logger, net_input


logger = get_logger(__file__)
TIMEOUT = 10
BUF_SIZE = 4096
MANUAL_LOGIN = 'manual'
AUTO_LOGIN = 'auto'


class ProxyServer:
    def __init__(self, client, login_from):
        self.client = client
        self.server = None
        self.login_from = login_from
        self.connecting = True
        self.stop_event = threading.Event()

    def get_system_user_auth(self, system_user):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        password, private_key = \
            app_service.get_system_user_auth_info(system_user)
        if system_user.login_mode == MANUAL_LOGIN or (not password and not private_key):
            prompt = "{}'s password: ".format(system_user.username)
            password = net_input(self.client, prompt=prompt, sensitive=True)
        system_user.password = password
        system_user.private_key = private_key

    def proxy(self, asset, system_user):
        if asset.protocol != system_user.protocol:
            msg = 'System user <{}> and asset <{}> protocol are inconsistent.'.format(
                system_user.name, asset.hostname
            )
            self.client.send(warning(wr(msg, before=1, after=0)))
            return

        if system_user.login_mode == MANUAL_LOGIN and not system_user.username:
            system_user_name = net_input(self.client, prompt='username: ', before=1)
            system_user.username = system_user_name

        self.get_system_user_auth(system_user)
        self.send_connecting_message(asset, system_user)
        self.server = self.get_server_conn(asset, system_user)
        if self.server is None:
            return
        command_recorder = current_app.new_command_recorder()
        replay_recorder = current_app.new_replay_recorder()
        session = Session(
            self.client, self.server, self.login_from,
            command_recorder=command_recorder,
            replay_recorder=replay_recorder,
        )
        current_app.add_session(session)
        self.watch_win_size_change_async()
        session.bridge()
        self.stop_event.set()
        self.end_watch_win_size_change()
        current_app.remove_session(session)

    def validate_permission(self, asset, system_user):
        """
        验证用户是否有连接改资产的权限
        :return: True or False
        """
        return app_service.validate_user_asset_permission(
            self.client.user.id, asset.id, system_user.id
        )

    def get_server_conn(self, asset, system_user):
        logger.info("Connect to {}".format(asset.hostname))
        if not self.validate_permission(asset, system_user):
            self.client.send(warning('No permission'))
            return None
        if system_user.protocol == asset.protocol == 'telnet':
            server = self.get_telnet_server_conn(asset, system_user)
        elif system_user.protocol == asset.protocol == 'ssh':
            server = self.get_ssh_server_conn(asset, system_user)
        else:
            server = None
        return server

    # Todo: Support telnet
    def get_telnet_server_conn(self, asset, system_user):
        telnet = TelnetConnection(asset, system_user, self.client)
        sock, msg = telnet.get_socket()
        if not sock:
            self.client.send(warning(wr(msg, before=1, after=0)))
            server = None
        else:
            server = TelnetServer(sock, asset, system_user)
        # self.client.send(b'\r\n')
        self.connecting = False
        return server

    def get_ssh_server_conn(self, asset, system_user):
        request = self.client.request
        term = request.meta.get('term', 'xterm')
        width = request.meta.get('width', 80)
        height = request.meta.get('height', 24)
        ssh = SSHConnection()
        chan, sock, msg = ssh.get_channel(
            asset, system_user, term=term, width=width, height=height
        )
        if not chan:
            self.client.send(warning(wr(msg, before=1, after=0)))
            server = None
        else:
            server = Server(chan, sock, asset, system_user)
        self.connecting = False
        self.client.send(b'\r\n')
        return server

    def watch_win_size_change(self):
        while self.client.request.change_size_event.wait():
            if self.stop_event.is_set():
                break
            self.client.request.change_size_event.clear()
            width = self.client.request.meta.get('width', 80)
            height = self.client.request.meta.get('height', 24)
            logger.debug("Change win size: %s - %s" % (width, height))
            try:
                self.server.chan.resize_pty(width=width, height=height)
            except SSHException:
                break

    def watch_win_size_change_async(self):
        if not isinstance(self.server, Server):
            return
        thread = threading.Thread(target=self.watch_win_size_change)
        thread.daemon = True
        thread.start()

    def end_watch_win_size_change(self):
        self.client.request.change_size_event.set()

    def send_connecting_message(self, asset, system_user):
        def func():
            delay = 0.0
            self.client.send('Connecting to {}@{} {:.1f}'.format(
                system_user, asset, delay)
            )
            while self.connecting and delay < TIMEOUT:
                self.client.send('\x08\x08\x08{:.1f}'.format(delay).encode())
                time.sleep(0.1)
                delay += 0.1
        thread = threading.Thread(target=func)
        thread.start()
