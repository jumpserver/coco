# -*- coding: utf-8 -*-
#

"""
    coco.app
    ~~~~~~~~~

    This module implements a ssh server and proxy with backend server

    :copyright: (c) 2016 by Jumpserver Team.
    :license: GPLv2, see LICENSE for more details.
"""

from __future__ import unicode_literals
import os
import time
import sys
import threading
import traceback
import socket
import logging

import paramiko
from dotmap import DotMap

from jms import AppService
from jms.mixin import AppMixin

from . import BASE_DIR, __version__, wr, warning
from .ctx import request, g, _request_ctx_stack, _g_ctx_stack, _client_channel_ctx_stack, \
    Request, G
from .interface import SSHInterface
from .interactive import InteractiveServer
from .config import Config
from .logger import create_logger, get_logger

logger = logging.getLogger(__file__)


class Coco(AppMixin):
    config_class = Config
    default_config = {
        'NAME': 'coco',
        'BIND_HOST': '0.0.0.0',
        'LISTEN_PORT': 2222,
        'JUMPSERVER_ENDPOINT': 'http://localhost:8080',
        'DEBUG': True,
        'SECRET_KEY': None,
        'ACCESS_KEY': None,
        'ACCESS_KEY_ENV': 'COCO_ACCESS_KEY',
        'ACCESS_KEY_STORE': os.path.join(BASE_DIR, 'keys', '.access_key'),
        'LOG_LEVEL': 'DEBUG',
        'LOG_DIR': os.path.join(BASE_DIR, 'logs'),
        'ASSET_LIST_SORT_BY': 'ip',
        'SSH_PASSWORD_AUTH': True,
        'SSH_PUBLIC_KEY_AUTH': True,
        'HEATBEAT_INTERVAL': 5,
    }
    access_key_store = os.path.join(BASE_DIR, 'keys', '.secret_key')

    def __init__(self):
        self.config = self.config_class(defaults=self.default_config)
        self.sock = None
        self.app_service = None
        self.user_service = None
        self.root_path = BASE_DIR
        self.logger = None

    def bootstrap(self):
        self.logger = create_logger(self)
        self.app_service = AppService(app_name=self.config['NAME'],
                                      endpoint=self.config['JUMPSERVER_ENDPOINT'])
        self.app_auth()
        while True:
            if self.app_service.check_auth():
                logger.info('App auth passed')
                break
            else:
                logger.warn('App auth failed, Access key error or need admin active it')
            time.sleep(5)
        self.heatbeat()

    def handle_ssh_request(self, client, addr):
        _request_ctx_stack.push(DotMap({'request': Request({'client': client, 'remote_addr': addr[0]})}))
        _g_ctx_stack.push(DotMap({'g': G({})}))
        logger.info("Get ssh request from %s" % request.remote_addr)
        transport = paramiko.Transport(request.client, gss_kex=False)
        try:
            transport.load_server_moduli()
        except:
            logger.warning('Failed to load moduli -- gex will be unsupported.')
            raise

        transport.add_server_key(SSHInterface.get_host_key())
        ssh_interface = SSHInterface(self, request.raw, g.raw)

        try:
            transport.start_server(server=ssh_interface)
        except paramiko.SSHException:
            logger.warning('SSH negotiation failed.')

        _client_channel = transport.accept(20)
        _client_channel_ctx_stack.push(DotMap({'client_channel': _client_channel}))
        if _client_channel is None:
            logger.warning('No ssh channel get.')
            sys.exit(1)

        # ssh_interface.shell_event.wait(1)
        # ssh_interface.command_event.wait(1)
        if ssh_interface.shell_event.is_set():
            logger.info('Client asked for a shell.')
            InteractiveServer(self).run()

        if ssh_interface.command_event.is_set():
            _client_channel.send(wr(warning('We are not support execute command now')))
            _client_channel.close()
            sys.exit(2)

        while True:
            if getattr(request, 'user'):
                break
            else:
                time.sleep(0.2)

    def run_forever(self, **kwargs):
        self.bootstrap()

        host = kwargs.pop('host', None) or self.config['BIND_HOST']
        port = kwargs.pop('port', None) or self.config['LISTEN_PORT']

        self.sock = sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(5)

        print(time.ctime())
        print('Coco version %s, more see https://www.jumpserver.org' % __version__)
        print('Starting ssh server at %(host)s:%(port)s' % {'host': host, 'port': port})
        print('Quit the server with CONTROL-C.')

        while True:
            try:
                client, addr = sock.accept()
                thread = threading.Thread(target=self.handle_ssh_request, args=(client, addr))
                thread.daemon = True
                thread.start()
            except Exception as e:
                logger.error('Bind server failed: ' + str(e))
                traceback.print_exc()
                sys.exit(1)

    def close(self):
        self.sock.close()
