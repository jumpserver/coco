#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import paramiko
import os
import threading
import logging

from jms import AppService

from . import BASE_DIR
from .utils import ssh_key_gen


class SSHInterface(paramiko.ServerInterface):
    """Use this ssh interface to implement a ssh server

    More see paramiko ssh server demo
    https://github.com/paramiko/paramiko/blob/master/demos/demo_server.py
    """
    host_key_path = os.path.join(BASE_DIR, 'keys', 'host_rsa_key')

    def __init__(self, app, request):
        self.app = app
        self.service = app.user_service
        self.request = request
        self.shell_event = threading.Event()
        self.command_event = threading.Event()
        self.request.change_channel_size_event = threading.Event()

    @classmethod
    def host_key(cls):
        return cls.get_host_key()

    @classmethod
    def get_host_key(cls):
        logging.debug("Get ssh server host key")
        if not os.path.isfile(cls.host_key_path):
            cls.host_key_gen()
        return paramiko.RSAKey(filename=cls.host_key_path)

    @classmethod
    def host_key_gen(cls):
        logging.debug("Generate ssh server host key")
        ssh_key, ssh_pub_key = ssh_key_gen()
        with open(cls.host_key_path, 'w') as f:
            f.write(ssh_key)

    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        user, token = self.service.login(username=username, password=password,
                                         remote_addr=self.request.host, login_type='T')
        if user:
            self.request.user = user
            self.service.auth(token=token)
            self.app.logger.info('Accepted password for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.request.host,
                'port': self.request.port,
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            self.app.logger.info('Authentication password failed for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.request.host,
                'port': self.request.port,
            })
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, public_key):
        public_key_s = public_key.get_base64()
        user, token = self.service.login(username=username, public_key=public_key_s, remote_addr=self.request.host)

        if user:
            self.service.auth(token=token)
            self.request.user = user
            logging.info('Accepted public key for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.request.host,
                'port': self.request.port,
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            logging.info('Authentication public key failed for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.request.host,
                'port': self.request.port,
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
        self.shell_event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height,
                                     pixelwidth, pixelheight, modes):
        self.request.channel_width = width
        self.request.channel_height = height
        return True

    def check_channel_exec_request(self, channel, command):
        self.request.command = command
        print(command)
        self.command_event.set()
        return True

    def check_channel_subsystem_request(self, channel, name):
        return super(SSHInterface, self).check_channel_subsystem_request(channel, name)

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        self.request.change_channel_size_event.set()
        self.request.channel_width = width
        self.request.channel_height = height
        return True