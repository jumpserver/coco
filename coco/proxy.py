#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import socket
import threading
import time
import weakref
import paramiko
from paramiko.ssh_exception import SSHException

from .session import Session
from .models import Server
from .utils import wrap_with_line_feed as wr, wrap_with_warning as warning, \
    get_private_key_fingerprint, get_logger


logger = get_logger(__file__)
TIMEOUT = 8
BUF_SIZE = 4096


class ProxyServer:
    def __init__(self, app, client):
        self._app = weakref.ref(app)
        self.client = client
        self.request = client.request
        self.server = None
        self.connecting = True

    @property
    def app(self):
        return self._app()

    def proxy(self, asset, system_user):
        self.send_connecting_message(asset, system_user)
        self.server = self.get_server_conn(asset, system_user)
        if self.server is None:
            return
        command_recorder = self.app.new_command_recorder()
        replay_recorder = self.app.new_replay_recorder()
        session = Session(
            self.client, self.server,
            command_recorder=command_recorder,
            replay_recorder=replay_recorder,
        )
        self.app.add_session(session)
        self.watch_win_size_change_async()
        session.bridge()
        self.app.remove_session(session)

    def validate_permission(self, asset, system_user):
        """
        验证用户是否有连接改资产的权限
        :return: True or False
        """
        return self.app.service.validate_user_asset_permission(
            self.client.user.id, asset.id, system_user.id
        )

    def get_system_user_auth(self, system_user):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        system_user.password, system_user.private_key = \
            self.app.service.get_system_user_auth_info(system_user)

    def get_server_conn(self, asset, system_user):
        logger.info("Connect to {}".format(asset.hostname))
        if not self.validate_permission(asset, system_user):
            self.client.send(warning('No permission'))
            return None
        self.get_system_user_auth(system_user)
        if True:
            server = self.get_ssh_server_conn(asset, system_user)
        else:
            server = self.get_ssh_server_conn(asset, system_user)
        return server

    # Todo: Support telnet
    def get_telnet_server_conn(self, asset, system_user):
        pass

    def get_ssh_server_conn(self, asset, system_user):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                asset.ip, port=asset.port, username=system_user.username,
                password=system_user.password, pkey=system_user.private_key,
                timeout=TIMEOUT, compress=True, auth_timeout=10,
                look_for_keys=False
            )
        except (paramiko.AuthenticationException, paramiko.BadAuthenticationType):
            admins = self.app.config['ADMINS'] or 'administrator'
            self.client.send(warning(wr(
                "Authenticate with server failed, contact {}".format(admins),
                before=1, after=0
            )))
            password_short = "None"
            key_fingerprint = "None"
            if system_user.password:
                password_short = system_user.password[:5] + (len(system_user.password)-5) * '*'
            if system_user.private_key:
                key_fingerprint = get_private_key_fingerprint(system_user.private_key)

            logger.error("Connect {}@{}:{} auth failed, password: {}, key: {}".format(
                system_user.username, asset.ip, asset.port,
                password_short, key_fingerprint,
            ))
            return None
        except socket.error as e:
            self.client.send(wr(" {}".format(e)))
            return None
        finally:
            self.connecting = False
            self.client.send(b'\r\n')

        term = self.request.meta.get('term', 'xterm')
        width = self.request.meta.get('width', 80)
        height = self.request.meta.get('height', 24)
        chan = ssh.invoke_shell(term, width=width, height=height)
        return Server(chan, asset, system_user)

    def watch_win_size_change(self):
        while self.request.change_size_event.wait():
            self.request.change_size_event.clear()
            width = self.request.meta.get('width', 80)
            height = self.request.meta.get('height', 24)
            logger.debug("Change win size: %s - %s" % (width, height))
            try:
                self.server.chan.resize_pty(width=width, height=height)
            except SSHException:
                break

    def watch_win_size_change_async(self):
        thread = threading.Thread(target=self.watch_win_size_change)
        thread.daemon = True
        thread.start()

    def send_connecting_message(self, asset, system_user):
        def func():
            delay = 0.0
            self.client.send('Connecting to {}@{} {:.1f}'.format(system_user, asset, delay))
            while self.connecting and delay < TIMEOUT:
                self.client.send('\x08\x08\x08{:.1f}'.format(delay).encode('utf-8'))
                time.sleep(0.1)
                delay += 0.1
        thread = threading.Thread(target=func)
        thread.start()


