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
import os
import re
import time
import sys
import threading
import traceback
import socket
import select
import datetime
import re
import logging

import paramiko
from dotmap import DotMap
from jms import AppService, UserService
from jms.mixin import AppMixin

from . import BASE_DIR
from .interface import SSHInterface
from .utils import SSHServerException, control_char, TtyIOParser, wrap_with_line_feed as wr, \
    wrap_with_info as info, wrap_with_warning as warning, wrap_with_primary as primary, \
    wrap_with_title as title, compute_max_length as cml
from .config import Config
from .ctx import request
from .logger import create_logger

__version__ = '0.3.3'
logger = logging.getLogger(__file__)
ENTER_CHAR = ['\r', '\n', '\r\n']


class ProxyServer(object):
    """
    We are using this class proxy client channel (user) with backend channel

    When receive client input command, send to backend ssh channel
    and when receive output of command from backend, send to client

    We also record the command and result to database for audit

    """
    output_data = b''
    history = {}

    def __init__(self, app):
        self.app = app
        self.client_channel = request.client_channel
        self.asset = request.asset
        self.app_service = app.app_service
        self.user_service = app.user_service
        self.system_user = request.system_user
        self.backend_channel = None
        self.ssh = None
        # Whether the terminal in input mode or output mode
        self.in_input_mode = True
        # If is first input, will clear the output data: ssh banner and PS1
        self.is_first_input = True
        # This ssh session command serial no
        self.cms_no = 0
        self.in_vim_mode = False
        self.vim_pattern = re.compile(r'\x1b\[\?1049', re.X)
        self.input = ''
        self.output = ''

    @staticmethod
    def is_finish_input(s):
        for char in s:
            if char in ENTER_CHAR:
                return True
        return False

    def get_output(self):
        if self.in_input_mode is False:
            parser = TtyIOParser(width=request.channel_width,
                                 height=request.channel_height)
            self.output = parser.parse_output(self.__class__.output_data)
            print('>' * 10 + 'Output' + '<' * 10)
            print(self.output)
            print('>' * 10 + 'End output' + '<' * 10)
            if self.input:
                # task.create_command_log.delay(task, self.no, self.input, self.output,
                #                               request.proxy_log_id, datetime.datetime.utcnow())
                self.cms_no += 1

    def get_input(self, client_data):
        if self.is_finish_input(client_data):
            vim_match = self.vim_pattern.findall(self.__class__.output_data)
            if vim_match:
                if self.in_vim_mode or len(vim_match) == 2:
                    self.in_vim_mode = False
                else:
                    self.in_vim_mode = True

            if not self.in_vim_mode:
                parser = TtyIOParser(width=request.channel_width,
                                     height=request.channel_height)
                self.input = parser.parse_input(self.__class__.output_data)
                print('#' * 10 + 'Command' + '#' * 10)
                print(self.input)
                print('#' * 10 + 'End command' + '#' * 10)

            self.in_input_mode = False

    def validate_user_permission(self, asset, system_user):
        assets = self.user_service.get_user_assets_granted(request.user)
        for a in assets:
            if asset.id == a.id:
                for s in asset.system_users:
                    if system_user.id == s.id:
                        return True
        return False

    def get_asset_auth(self, system_user):
        return self.app_service.get_asset_auth(system_user)

    def connect(self, term=b'xterm', width=80, height=24, timeout=10):
        asset = self.asset
        system_user = self.system_user
        if not self.validate_user_permission(asset, system_user):
            logging.warning('User %s have no permission connect %s with %s' % (request.user.username,
                                                                              asset.ip, system_user.username))
            return None
        self.ssh = ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password, private_key = self.get_asset_auth(self.system_user)
        data = DotMap({"username": request.user.username, "name": request.user.name,
                       "hostname": self.asset.hostname, "ip": self.asset.ip,
                       "system_user": self.system_user.username,  "login_type": "S",
                       "date_start": datetime.datetime.utcnow(), "was_failed": 0})
        # request.proxy_log_id = proxy_log_id = api.create_proxy_log(data)
        try:
            self.client_channel.send(wr('Connecting %s@%s:%s ... ' % (system_user.username, asset.ip, asset.port)))
            ssh.connect(hostname=asset.ip, port=asset.port, username=system_user.username,
                        password=password, pkey=private_key, look_for_keys=False,
                        allow_agent=True, compress=True, timeout=timeout)

        except (paramiko.AuthenticationException, paramiko.ssh_exception.SSHException):
            msg = 'Connect backend server %s failed: %s' % (asset.ip, 'Auth failed')
            logging.warning(msg)
            failed = True

        except socket.error:
            msg = 'Connect backend server %s failed: %s' % (asset.ip, 'Timeout')
            logging.warning(msg)
            failed = True
        else:
            msg = 'Connect backend server %(username)s@%(host)s:%(port)s successfully' % {
                       'username': system_user.username,
                       'host': asset.ip,
                       'port': asset.port}
            failed = False
            logging.info(msg)

        if failed:
            self.client_channel.send(wr(warning(msg+'\r\n')))
            data = DotMap({
                # "proxy_log_id": proxy_log_id,
                "proxy_log_id": 1,
                "date_finished": datetime.datetime.utcnow(),
                "was_failed": 1
            })
            # api.finish_proxy_log(data)
            return None

        self.backend_channel = channel = ssh.invoke_shell(term=term, width=width, height=height)
        channel.settimeout(100)
        channel.host = asset.ip
        channel.port = asset.port
        channel.username = system_user.username
        return channel

    def proxy(self):
        client_channel = self.client_channel
        self.backend_channel = backend_channel = self.connect()

        if backend_channel is None:
            return

        while True:
            r, w, x = select.select([client_channel, backend_channel], [], [])

            if request.change_channel_size_event.is_set():
                request.change_channel_size_event.clear()
                backend_channel.resize_pty(width=request.channel_width,
                                           height=request.channel.channel_height)

            if client_channel in r:
                # Get output of the command
                self.get_output()

                client_data = client_channel.recv(1024)
                self.in_input_mode = True
                self.is_first_input = False

                # Get command
                self.get_input(client_data)

                if len(client_data) == 0:
                    print(request)
                    logging.info('Logout from ssh server %(host)s: %(username)s' % {
                        'host': request.addr[0],
                        'username': request.username,
                    })
                    break
                backend_channel.send(client_data)

            if backend_channel in r:
                backend_data = backend_channel.recv(1024)
                if len(backend_data) == 0:
                    client_channel.send(wr('Disconnect from %s' % backend_channel.host))
                    logging.info('Logout from backend server %(host)s: %(username)s' % {
                        'host': backend_channel.host,
                        'username': backend_channel.username,
                    })
                    break
                if not self.is_first_input:
                    self.__class__.output_data += backend_data
                client_channel.send(backend_data)
        data = DotMap({
                "proxy_log_id": request.proxy_log_id,
                "date_finished": datetime.datetime.utcnow(),
                })
        # api.finish_proxy_log(data)


class InteractiveServer(object):
    """Hi, This is a interactive server, show a navigation, accept user input,
    and do [proxy to backend server, execute command, upload file, or other interactively]
    """

    SPECIAL_CHAR = {'\x08': '\x08\x1b[K', '\x7f': '\x08\x1b[K'}

    def __init__(self, app):
        self.app = app
        self.user_service = app.user_service
        self.app_service = app.app_service
        self.client_channel = request.client_channel
        self.backend_server = None
        self.backend_channel = None
        self.assets = None  # self.get_user_assets_granted()
        self.asset_groups = None  # self.get_user_asset_groups_granted()
        self.search_result = []

    def display_banner(self):
        client_channel = self.client_channel
        client_channel.send(control_char.clear)
        msg = u"""\n\033[1;32m  %s, 欢迎使用Jumpserver开源跳板机系统  \033[0m\r\n\r
        1) 输入 \033[32mID\033[0m 直接登录 或 输入\033[32m部分 IP,主机名,备注\033[0m 进行搜索登录(如果唯一).\r
        2) 输入 \033[32m/\033[0m + \033[32mIP, 主机名 or 备注 \033[0m搜索. 如: /ip\r
        3) 输入 \033[32mP/p\033[0m 显示您有权限的主机.\r
        4) 输入 \033[32mG/g\033[0m 显示您有权限的主机组.\r
        5) 输入 \033[32mG/g\033[0m\033[0m + \033[32m组ID\033[0m 显示该组下主机. 如: g1\r
        6) 输入 \033[32mE/e\033[0m 批量执行命令.\r
        7) 输入 \033[32mU/u\033[0m 批量上传文件.\r
        8) 输入 \033[32mD/d\033[0m 批量下载文件.\r
        9) 输入 \033[32mH/h\033[0m 帮助.\r
        0) 输入 \033[32mQ/q\033[0m 退出.\r\n""" % request.user.username
        client_channel.send(msg)

        # client_channel.send('\r\n\r\n\t\tWelcome to use Jumpserver open source system !\r\n\r\n')
        # client_channel.send('If you find some bug please contact us <ibuler@qq.com>\r\n')
        # client_channel.send('See more at https://www.jumpserver.org\r\n\r\n')

    def input(self, prompt='Opt> '):
        """Make a prompt let user input, and get user input content"""

        input_ = b''
        parser = TtyIOParser(request.channel_width, request.channel_height)
        self.client_channel.send(wr(prompt, before=1, after=0))
        while True:
            r, w, x = select.select([self.client_channel], [], [])
            if self.client_channel in r:
                data = self.client_channel.recv(1024)

                if data in self.__class__.SPECIAL_CHAR:
                    # If input words less than 0, should send 'BELL'
                    if len(parser.parse_input(input_)) > 0:
                        data = self.__class__.SPECIAL_CHAR[data]
                        input_ += data
                    else:
                        data = b'\x07'
                    self.client_channel.send(data)
                    continue

                # If user type ENTER we should get user input
                if data in ENTER_CHAR:
                    self.client_channel.send(wr('', after=2))
                    option = parser.parse_input(input_)
                    return option
                else:
                    self.client_channel.send(data)
                    input_ += data

    def dispatch(self, twice=False):
        option = self.input()
        if option in ['P', 'p', '\r', '\n']:
            self.search_and_display('')
        elif option.startswith('/'):
            option = option.lstrip('/')
            self.search_and_display(option=option)
        elif option in ['g', 'G']:
            self.display_asset_groups()
        elif re.match(r'g\d+', option):
            self.display_asset_group_asset(option)
        elif option in ['q', 'Q']:
            self.logout()
            sys.exit()
        elif option in ['h', 'H']:
            return self.display_banner()
        else:
            return self.search_and_proxy(option=option, from_result=twice)

    def search_assets(self, option, from_result=False):
        option = option.strip().lower()
        if option:
            if from_result:
                assets = self.search_result
            else:
                assets = self.assets

            id_search_result = []
            if option.isdigit() and int(option) < len(assets):
                id_search_result = [assets[int(option)]]

            if id_search_result:
                self.search_result = id_search_result
            else:
                self.search_result = [
                    asset for asset in assets if option == asset.ip
                ] or [
                    asset for asset in assets
                        if option in asset.ip or
                           option in asset.hostname.lower() or
                           option in asset.comment.lower()
                ]
        else:
            self.search_result = self.assets

    def display_assets(self):
        self.search_and_display('')

    def display_asset_groups(self):
        self.asset_groups = self.app_service.get_user_asset_groups_granted(request.user)
        name_max_length = cml([asset_group.name for asset_group in self.asset_groups], max_length=20)
        comment_max_length = cml([asset_group.comment for asset_group in self.asset_groups], max_length=30)
        line = '[%-3s] %-' + str(name_max_length) + 's %-6s  %-' + str(comment_max_length) + 's'
        self.client_channel.send(wr(title(line % ('ID', 'Name', 'Assets', 'Comment'))))
        for index, asset_group in enumerate(self.asset_groups):
            self.client_channel.send(wr(line % (index, asset_group.name,
                                                asset_group.assets_amount,
                                                asset_group.comment[:comment_max_length])))
        self.client_channel.send(wr(''))

    def display_asset_group_asset(self, option):
        match = re.match(r'g(\d+)', option)
        if match:
            index = match.groups()[0]

            if index.isdigit() and len(self.asset_groups) > int(index):
                asset_group = self.asset_groups[int(index)]
                self.search_result = self.user_service.get_user_asset_group_assets(request.user, asset_group.id)
                self.display_search_result()
                self.dispatch(twice=True)

        self.client_channel.send(wr(warning('No asset group match, please input again')))

    def display_search_result(self):
        if not self.assets:
            self.assets = api.get_user_assets_granted(request.user)
        if not self.search_result:
            self.search_result = self.assets

        hostname_max_length = cml([asset.hostname for asset in self.search_result])
        line = '[%-4s] %-16s %-5s %-' + str(hostname_max_length) + 's %-10s %s'
        self.client_channel.send(wr(title(line % ('ID', 'IP', 'Port', 'Hostname', 'Username', 'Comment'))))

        for index, asset in enumerate(self.search_result):
            system_users = '[' + ', '.join([system_user.username for system_user in asset.system_users]) + ']'
            self.client_channel.send(wr(line % (index, asset.ip, asset.port, asset.hostname,
                                                system_users, asset.comment)))
        self.client_channel.send(wr(''))

    def search_and_display(self, option):
        self.search_assets(option=option)
        self.display_search_result()

    def search_and_proxy(self, option, from_result=False):
        self.search_assets(option=option, from_result=from_result)
        if len(self.search_result) == 1:
            request.asset = asset = self.search_result[0]
            if len(asset.system_users) == 1:
                system_user = asset.system_users[0]
            else:
                self.client_channel.send(wr(primary('More than one system user granted, select one')))
                while True:
                    for index, system_user in enumerate(asset.system_users):
                        self.client_channel.send(wr('[%s] %s' % (index, system_user.username)))

                    option = self.input(prompt='System user> ')
                    if option.isdigit() and int(option) < len(asset.system_users):
                        system_user = asset.system_users[int(option)]
                        break
                    elif option in ['q', 'Q']:
                        return
                    else:
                        self.client_channel.send(wr(warning('No system user match, please input again')))
            request.system_user = system_user
            self.return_to_proxy(asset, system_user)
        elif len(self.search_result) == 0:
            self.client_channel.send(wr(warning('No asset match, please input again')))
            return self.dispatch()
        else:
            self.client_channel.send(wr(primary('Search result is not unique, select below or search again'), after=2))
            self.display_search_result()
            self.dispatch(twice=True)

    def return_to_proxy(self, asset, system_user):
        proxy_server = ProxyServer(self.client_channel, asset, system_user)
        proxy_server.proxy()

    def run(self):
        if self.client_channel is None:
            request.client.close()
            return

        self.display_banner()
        while True:
            try:
                self.dispatch()
            except socket.error:
                self.logout()
                break

    def logout(self):
        logging.info('Logout from jumpserver %(host)s: %(username)s' % {
            'host': request.addr[0],
            'username': request.username,
        })
        if request.get('proxy_log_id', ''):
            data = DotMap({
                'proxy_log_id': request.proxy_log_id,
                'date_finished': datetime.datetime.utcnow(),
            })
            # api.finish_proxy_log(data)
        self.client_channel.close()
        del self


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
        # self.terminal_id = ''

    def bootstrap(self):
        self.logger = create_logger(self)
        self.app_service = AppService(app_name=self.config['NAME'],
                                      endpoint=self.config['JUMPSERVER_ENDPOINT'])
        self.user_service = UserService(app_name=self.config['NAME'],
                                        endpoint=self.config['JUMPSERVER_ENDPOINT'])
        self.app_auth()
        while True:
            if self.check_auth():
                logger.info('App auth passed')
                break
            else:
                logger.warn('App auth failed, Access key error or need admin active it')
            time.sleep(5)
        self.heatbeat()

    def handle_ssh_request(self, client, addr):
        logging.info("Get ssh request from %(host)s:%(port)s" % {
            'host': addr[0],
            'port': addr[1],
        })
        request.client = client
        request.host, request.port = addr
        transport = paramiko.Transport(client, gss_kex=False)
        try:
            transport.load_server_moduli()
        except:
            logging.warning('Failed to load moduli -- gex will be unsupported.')
            raise

        transport.add_server_key(SSHInterface.get_host_key())
        ssh_interface = SSHInterface(self, request)

        try:
            transport.start_server(server=ssh_interface)
        except paramiko.SSHException:
            logging.warning('SSH negotiation failed.')

        request.client_channel = client_channel = transport.accept(20)
        if client_channel is None:
            logging.warning('No ssh channel get.')
            return None

        # ssh_interface.shell_event.wait(1)
        # ssh_interface.command_event.wait(1)
        if ssh_interface.shell_event.is_set():
            logging.info('Client asked for a shell.')
            InteractiveServer(self).run()

        if ssh_interface.command_event.is_set():
            client_channel.send(wr(warning('We are not support execute command now')))
            client_channel.close()
            sys.exit(1)

        while True:
            if getattr(request, 'user'):
                break
            else:
                time.sleep(0.2)
        return client_channel

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
                logging.error('Bind server failed: ' + str(e))
                traceback.print_exc()
                sys.exit(1)

    def close(self):
        self.sock.close()
