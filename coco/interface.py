#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import paramiko
import os
import threading
import logging

from jms import UserService
from . import PROJECT_DIR
from .utils import ssh_key_gen
from .globals import request


logger = logging.getLogger(__file__)


class SSHInterface(paramiko.ServerInterface):
    """使用paramiko提供的接口实现ssh server.

    More see paramiko ssh server demo
    https://github.com/paramiko/paramiko/blob/master/demos/demo_server.py
    """
    host_key_path = os.path.join(PROJECT_DIR, 'keys', 'host_rsa_key')
    start_check_auth = False

    def __init__(self, app, rc):
        self.app = app
        self.rc = rc
        rc.push()
        request.change_win_size_event = threading.Event()
        self.user_service = UserService(self.app.endpoint)

    @classmethod
    def get_host_key(cls):
        logger.debug("Get ssh server host key")
        if not os.path.isfile(cls.host_key_path):
            cls.host_key_gen()
        return paramiko.RSAKey(filename=cls.host_key_path)

    @classmethod
    def host_key_gen(cls):
        logger.debug("Generate ssh server host key")
        ssh_key, ssh_pub_key = ssh_key_gen()
        with open(cls.host_key_path, 'w') as f:
            f.write(ssh_key)

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth(self, username, password=None, public_key=None):
        self.rc.push()
        data = {
            "username": username,
            "password": password,
            "public_key": public_key,
            "login_type": 'ST'
        }
        logger.debug("Start check auth")
        user, token = self.user_service.login(data)
        result = False
        if user:
            request.user = user
            self.user_service.auth(token=token)
            result = True
        logger.debug("Finish check auth")
        return result

    def check_auth_password(self, username, password):
        if self.check_auth(username, password=password):
            logger.info('Accepted password for %(username)s from %(host)s' % {
                'username': username,
                'host': request.environ['REMOTE_ADDR'],
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            logger.info('Authentication password failed for '
                        '%(username)s from %(host)s' % {
                            'username': username,
                            'host': request.environ['REMOTE_ADDR'],
                         })
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, public_key):
        """登录时首先会使用公钥认证, 会自动扫描家目录的私钥,
        验证账号密码, paramiko会启动新的线程, 所以需要push request context
        """
        public_key_s = public_key.get_base64()
        if self.check_auth(username, public_key=public_key_s):
            logger.info('Accepted public key for %(username)s from %(host)s' % {
                'username': username,
                'host': request.environ['REMOTE_ADDR'],
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            logger.info('Authentication public key failed for '
                        '%(username)s from %(host)s' % {
                            'username': username,
                            'host': request.environ['REMOTE_ADDR'],
            })
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        auth_method_list = []
        if self.app.config['SSH_PASSWORD_AUTH']:
            auth_method_list.append('password')
        if self.app.config['SSH_PUBLIC_KEY_AUTH']:
            auth_method_list.append('publickey')
        return ','.join(auth_method_list)

    def check_channel_shell_request(self, channel):
        request.method = 'shell'
        return True

    def check_channel_pty_request(self, channel, term, width, height,
                                  pixelwidth, pixelheight, modes):
        request.win_width = channel.win_width = width
        request.win_height = channel.win_height = height
        return True

    def check_channel_exec_request(self, channel, command):
        request.method = 'exec'
        return True

    def check_channel_subsystem_request(self, channel, name):
        request.method = 'subsystem'
        return super(SSHInterface, self)\
            .check_channel_subsystem_request(channel, name)

    def check_channel_window_change_request(self, channel, width,
                                            height, pixelwidth, pixelheight):
        request.win_width = channel.win_width = width
        request.win_width = channel.win_height = height
        request.change_win_size_event.set()
        return True
