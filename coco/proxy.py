#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import threading
import time
import copy

from .session import Session
from .models import Server, TelnetServer
from .const import (
    PERMS_ACTION_NAME_CONNECT, MANUAL_LOGIN
)
from .connection import SSHConnection, TelnetConnection
from .service import app_service
from .conf import config
from .utils import (
    wrap_with_line_feed as wr, wrap_with_warning as warning, ugettext as _,
    get_logger, net_input, ignore_error
)


logger = get_logger(__file__)
BUF_SIZE = 4096


class ProxyServer:
    def __init__(self, client, asset, system_user):
        self.client = client
        self.asset = asset
        self.system_user = copy.deepcopy(system_user)
        self.server = None
        self.connecting = True

    def get_system_user_auth_or_manual_set(self):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        password, private_key = \
            app_service.get_system_user_auth_info(self.system_user, self.asset)
        if self.system_user.login_mode == MANUAL_LOGIN \
                or (not password and not private_key):
            prompt = "{}'s password: ".format(self.system_user.username)
            password = net_input(self.client, prompt=prompt, sensitive=True)
            private_key = None
        self.system_user.password = password
        self.system_user.private_key = private_key

    def check_protocol(self):
        if not self.asset.has_protocol(self.system_user.protocol):
            msg = _('Asset {} do not contain system user {} protocol {}')
            msg = msg.format(
                self.asset.hostname, self.system_user.name, self.system_user.protocol
            )
            self.client.send_unicode(warning(wr(msg, before=1, after=0)))
            return False
        return True

    def get_system_user_username_if_need(self):
        if self.system_user.login_mode == MANUAL_LOGIN and \
                not self.system_user.username:
            username = net_input(self.client, prompt='username: ', before=1)
            self.system_user.username = username
            return True
        return False

    def proxy(self):
        if not self.check_protocol():
            return
        self.server = self.get_server_conn_from_cache()
        if not self.server:
            self.server = self.get_server_conn()
        if self.server is None:
            return
        if self.client.closed:
            self.server.close()
            return
        session = Session.new_session(self.client, self.server)
        if not session:
            msg = _("Connect with api server failed")
            logger.error(msg)
            self.client.send_unicode(msg)
            self.server.close()
            return

        try:
            session.bridge()
        finally:
            Session.remove_session(session.id)
            self.server.close()
            msg = 'Session end, total {} now'.format(
                len(Session.sessions),
            )
            logger.info(msg)

    def validate_permission(self):
        """
        验证用户是否有连接改资产的权限
        :return: True or False
        """
        kwargs = {
            'user_id': self.client.user.id,
            'asset_id': self.asset.id,
            'system_user_id': self.system_user.id,
            'action_name': PERMS_ACTION_NAME_CONNECT
        }
        return app_service.validate_user_asset_permission(**kwargs)

    def get_server_conn_from_cache(self):
        server = None
        if self.system_user.protocol == 'ssh':
            server = self.get_ssh_server_conn(cache=True)
        return server

    def get_server_conn(self):
        # 与获取连接
        self.get_system_user_username_if_need()
        self.get_system_user_auth_or_manual_set()
        self.send_connecting_message()
        logger.info("Connect to {}:{} ...".format(self.asset.hostname, self.asset.ssh_port))
        if not self.validate_permission():
            msg = _('No permission')
            self.client.send_unicode(warning(wr(msg, before=2, after=0)))
            server = None
        elif self.system_user.protocol == 'telnet':
            server = self.get_telnet_server_conn()
        elif self.system_user.protocol == 'ssh':
            server = self.get_ssh_server_conn()
        else:
            server = None
        self.client.send(b'\r\n')
        self.connecting = False
        return server

    def get_telnet_server_conn(self):
        telnet = TelnetConnection(self.asset, self.system_user, self.client)
        sock, msg = telnet.get_socket()
        if not sock:
            self.client.send_unicode(warning(wr(msg, before=1, after=0)))
            server = None
        else:
            server = TelnetServer(sock, self.asset, self.system_user)
        return server

    def get_ssh_server_conn(self, cache=False):
        request = self.client.request
        term = request.meta.get('term', 'xterm')
        width = request.meta.get('width', 80)
        height = request.meta.get('height', 24)

        if cache:
            conn = SSHConnection.new_connection_from_cache(
                self.client.user, self.asset, self.system_user
            )
            if not conn or not conn.is_active:
                return None
            else:
                # 采用复用连接创建session时，系统用户用户名如果为空，创建session-400
                self.system_user = conn.system_user
        else:
            conn = SSHConnection.new_connection(
                self.client.user, self.asset, self.system_user
            )
        chan = conn.get_channel(term=term, width=width, height=height)
        if not chan:
            self.client.send_unicode(warning(wr(conn.error, before=1, after=0)))
            server = None
        else:
            server = Server(chan, conn, self.asset, self.system_user)
        return server

    def send_connecting_message(self):
        @ignore_error
        def func():
            delay = 0.0
            msg = _('Connecting to {}@{} {:.1f}').format(
                self.system_user, self.asset, delay
            )
            self.client.send_unicode(msg)
            while self.connecting and delay < config['SSH_TIMEOUT']:
                if 0 <= delay < 10:
                    self.client.send_unicode('\x08\x08\x08{:.1f}'.format(delay))
                else:
                    self.client.send_unicode('\x08\x08\x08\x08{:.1f}'.format(delay))
                time.sleep(0.1)
                delay += 0.1
        thread = threading.Thread(target=func)
        thread.start()
