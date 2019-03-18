#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import threading
import time

from .session import Session
from .models import Server, TelnetServer
from .connection import SSHConnection, TelnetConnection
from .service import app_service
from .conf import config
from .utils import wrap_with_line_feed as wr, wrap_with_warning as warning, \
     get_logger, net_input, ugettext as _, ignore_error


logger = get_logger(__file__)
BUF_SIZE = 4096
MANUAL_LOGIN = 'manual'
AUTO_LOGIN = 'auto'


class ProxyServer:
    def __init__(self, client, asset, system_user):
        self.client = client
        self.asset = asset
        self.system_user = system_user
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
        if self.asset.protocol != self.system_user.protocol:
            msg = 'System user <{}> and asset <{}> protocol are inconsistent.'.format(
                self.system_user.name, self.asset.hostname
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
        self.get_system_user_username_if_need()
        self.get_system_user_auth_or_manual_set()
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
        return app_service.validate_user_asset_permission(
            self.client.user.id, self.asset.id, self.system_user.id
        )

    def get_server_conn(self):
        logger.info("Connect to {}:{} ...".format(self.asset.hostname, self.asset.port))
        self.send_connecting_message()
        if not self.validate_permission():
            self.client.send_unicode(warning(_('No permission')))
            server = None
        elif self.system_user.protocol == self.asset.protocol == 'telnet':
            server = self.get_telnet_server_conn()
        elif self.system_user.protocol == self.asset.protocol == 'ssh':
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

    def get_ssh_server_conn(self):
        request = self.client.request
        term = request.meta.get('term', 'xterm')
        width = request.meta.get('width', 80)
        height = request.meta.get('height', 24)
        ssh = SSHConnection()
        chan, sock, msg = ssh.get_channel(
            self.asset, self.system_user, term=term,
            width=width, height=height
        )
        if not chan:
            self.client.send_unicode(warning(wr(msg, before=1, after=0)))
            server = None
        else:
            server = Server(chan, sock, self.asset, self.system_user)
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
