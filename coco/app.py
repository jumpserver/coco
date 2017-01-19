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
import sys
import time
import threading
import traceback
import socket

import paramiko
from jms import AppService
from jms.mixin import AppMixin

from . import __version__
from .ctx import RequestContext, AppContext, Request, _AppCtxGlobals
from .globals import request, g
from .interface import SSHInterface
from .interactive import InteractiveServer
from .conf import ConfigAttribute, config
from .utils import wrap_with_line_feed as wr, wrap_with_warning as warning
from .logger import get_logger
from .service import service

logger = get_logger(__file__)


class Coco(AppMixin):
    request_class = Request
    app_ctx_globals_class = _AppCtxGlobals
    endpoint = ConfigAttribute('JUMPSERVER_ENDPOINT')
    debug = ConfigAttribute('DEBUG')
    host = ConfigAttribute('BIND_HOST')
    port = ConfigAttribute('LISTEN_PORT')

    def __init__(self, name=None):
        self._name = name
        self.config = config
        self.sock = None
        self.service = service

    @property
    def name(self):
        """获取app实例名称, 优先使用配置项"""
        if self.config['NAME']:
            return self.config['NAME']
        else:
            return self._name

    def app_context(self):
        return AppContext(self)

    def request_context(self, environ):
        return RequestContext(self, environ)

    def bootstrap(self):
        """运行之前准备一些动作, 创建日志, 实例化sdk, 认证service"""
        # self.service = AppService(app_name=self.name,
        #                           endpoint=self.endpoint,
        #                           config=self.config,
        #                           )
        # self.app_auth()
        # print('Using access key %s:***' % self.service.access_key.id)
        # while True:
        #     if self.service.is_authenticated():
        #         logger.info('App auth passed')
        #         break
        #     else:
        #         logger.warn('App auth failed, Access key error '
        #                     'or need admin active it')
        #     time.sleep(5)
        # self.heatbeat()
        pass

    def process_request(self, client, addr):
        rc = self.request_context({'REMOTE_ADDR': addr[0]})
        rc.push()
        logger.info("Get ssh request from %s" % request.environ['REMOTE_ADDR'])
        transport = paramiko.Transport(client, gss_kex=False)
        try:
            transport.load_server_moduli()
        except:
            logger.warning('Failed to load moduli -- gex will be unsupported.')
            raise

        transport.add_server_key(SSHInterface.get_host_key())
        # 将app和请求上下文传递过去, ssh_interface 处理ssh认证和建立连接
        ssh_interface = SSHInterface(self, rc)

        try:
            transport.start_server(server=ssh_interface)
        except paramiko.SSHException:
            logger.warning('SSH negotiation failed.')

        _client_channel = transport.accept(20)
        g.client_channel = _client_channel
        if _client_channel is None:
            logger.warning('No ssh channel get.')
            sys.exit(1)

        if request.method == 'shell':
            logger.info('Client asked for a shell.')
            InteractiveServer(self).run()
        elif request.method == 'command':
            _client_channel.send(wr(warning('We are not support command now')))
            _client_channel.close()
            sys.exit(2)
        else:
            _client_channel.send(wr(warning('Not support the request method')))
            _client_channel.close()
            sys.exit(2)

        while True:
            if request.user is not None:
                break
            else:
                time.sleep(0.2)

    def run_forever(self, **kwargs):
        self.bootstrap()
        host = kwargs.pop('host', None) or self.host
        port = kwargs.pop('port', None) or self.port

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
                thread = threading.Thread(target=self.process_request,
                                          args=(client, addr))
                thread.daemon = True
                thread.start()
            except Exception as e:
                logger.error('Start server failed: ' + str(e))
                traceback.print_exc()
                sys.exit(1)

    def close(self):
        self.sock.close()
