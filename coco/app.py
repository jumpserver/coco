# -*- coding: utf-8 -*-
#

"""
    coco
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

import paramiko

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
sys.path.append(os.path.dirname(BASE_DIR))
sys.path.append(PROJECT_DIR)

from config import config, TerminalConfig
from utils import get_logger, SSHServerException, control_char, ssh_key_gen, \
     wrap_with_line_feed as wr, TerminalApiRequest, Dict, TtyIOParser, \
     wrap_with_info as info, wrap_with_warning as warning, wrap_with_primary as primary, \
     wrap_with_title as title, compute_max_length as cml
from tasks import Task


CONFIG = config.get('terminal', TerminalConfig)
NAME = CONFIG.NAME
api = TerminalApiRequest(NAME)
task = Task(NAME)
logger = get_logger(__name__)
paramiko.util.log_to_file(os.path.join(PROJECT_DIR, 'logs', 'paramiko.log'))
ENTER_CHAR = ['\r', '\n', '\r\n']
# request save threading context
# use request.meta save request meta info
# request.meta = Dict{'user': {}, 'username', 'asset': {} or None, 'proxy_log_id': '' or None,
#                     'client_addr': (ip, port), 'client': client_sock, 'client_channel': <Channel object>,
#                     'backend_channel': <Channel object>,  'channel_width': '', 'channel_height': '',
#                     'command': ''}
request = threading.local()
g = type(b'Global', (), {'__getattr__': None, 'requests': {}})()


class SSHInterface(paramiko.ServerInterface):
    """Use this ssh interface to implement a ssh server

    More see paramiko ssh server demo
    https://github.com/paramiko/paramiko/blob/master/demos/demo_server.py
    """
    host_key_path = os.path.join(BASE_DIR, 'keys', 'host_rsa_key')

    def __init__(self):
        self.meta = request.meta
        self.shell_event = threading.Event()
        self.command_event = threading.Event()
        self.meta.change_channel_size_event = threading.Event()

    @classmethod
    def host_key(cls):
        return cls.get_host_key()

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

    def check_auth_password(self, username, password):
        user = api.login(username=username, password=password, remote_addr=self.meta.addr[0])
        if user:
            self.meta.user = user
            self.meta.username = username
            logger.info('Accepted password for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.meta.addr[0],
                'port': self.meta.addr[1],
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            logger.info('Authentication password failed for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.meta.addr[0],
                'port': self.meta.addr[1],
            })
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, public_key):
        public_key_s = public_key.get_base64()
        user = api.login(username=username, public_key=public_key_s, remote_addr=self.meta.addr[0])

        if user:
            self.meta.user = user
            self.meta.username = username
            logger.info('Accepted public key for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.meta.addr[0],
                'port': self.meta.addr[1],
            })
            return paramiko.AUTH_SUCCESSFUL
        else:
            logger.info('Authentication public key failed for %(username)s from %(host)s port %(port)s ' % {
                'username': username,
                'host': self.meta.addr[0],
                'port': self.meta.addr[1],
            })
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        auth_method_list = []
        if CONFIG.SSH_PASSWORD_AUTH:
            auth_method_list.append('password')
        if CONFIG.SSH_PUBLIC_KEY_AUTH:
            auth_method_list.append('publickey')
        return ','.join(auth_method_list)

    def check_channel_shell_request(self, channel):
        self.shell_event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height,
                                  pixelwidth, pixelheight, modes):
        self.meta.channel_width = width
        self.meta.channel_height = height
        return True

    def check_channel_exec_request(self, channel, command):
        self.meta.command = command
        print(command)
        self.command_event.set()
        return True

    def check_channel_subsystem_request(self, channel, name):
        return super(SSHInterface, self).check_channel_subsystem_request(channel, name)

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        self.meta.change_channel_size_event.set()
        self.meta.channel_width = width
        self.meta.channel_height = height
        return True


class ProxyServer(object):
    """
    We are using this class proxy client channel (user) with backend channel

    When receive client input command, send to backend ssh channel
    and when receive output of command from backend, send to client

    We also record the command and result to database for audit

    """
    output_data = b''
    history = {}

    def __init__(self, client_channel, asset, system_user):
        self.client_channel = client_channel
        self.asset = asset
        self.system_user = system_user
        self.backend_channel = None
        self.ssh = None
        # Whether the terminal in input mode or output mode
        self.in_input_mode = True
        # If is first input, will clear the output data: ssh banner and PS1
        self.is_first_input = True
        # This ssh session command serial no
        self.no = 0
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
            parser = TtyIOParser(width=request.meta.channel_width,
                                 height=request.meta.channel_height)
            self.output = parser.parse_output(self.__class__.output_data)
            print('>' * 10 + 'Output' + '<' * 10)
            print(self.output)
            print('>' * 10 + 'End output' + '<' * 10)
            if self.input:
                task.create_command_log.delay(task, self.no, self.input, self.output,
                                              request.meta.proxy_log_id, datetime.datetime.utcnow())
                self.no += 1
            del self.__class__.output_data
            self.__class__.output_data = b''

    def get_input(self, client_data):
        if self.is_finish_input(client_data):
            vim_match = self.vim_pattern.findall(self.__class__.output_data)
            if vim_match:
                if self.in_vim_mode or len(vim_match) == 2:
                    self.in_vim_mode = False
                else:
                    self.in_vim_mode = True

            if not self.in_vim_mode:
                parser = TtyIOParser(width=request.meta.channel_width,
                                     height=request.meta.channel_height)
                self.input = parser.parse_input(self.__class__.output_data)
                print('#' * 10 + 'Command' + '#' * 10)
                print(self.input)
                print('#' * 10 + 'End command' + '#' * 10)

            self.in_input_mode = False
            del self.__class__.output_data
            self.__class__.output_data = b''

    @staticmethod
    def validate_user_permission(asset, system_user):
        assets = api.get_user_assets_granted(request.meta.user)
        for a in assets:
            if asset.id == a.id:
                for s in asset.system_users:
                    if system_user.id == s.id:
                        return True
        return False

    @staticmethod
    def get_asset_auth(system_user):
        return api.get_asset_auth(system_user)

    def connect(self, term=b'xterm', width=80, height=24, timeout=10):
        asset = self.asset
        system_user = self.system_user
        if not self.validate_user_permission(asset, system_user):
            logger.warning('User %s have no permission connect %s with %s' % (request.meta.user.username,
                                                                              asset.ip, system_user.username))
            return None
        self.ssh = ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password, private_key = self.get_asset_auth(self.system_user)
        data = Dict({"username": request.meta.user.username, "name": request.meta.user.name,
                     "hostname": self.asset.hostname, "ip": self.asset.ip,
                     'system_user': self.system_user.username,  "login_type": 'S',
                     "date_start": datetime.datetime.utcnow(), "was_failed": 0})
        request.meta.proxy_log_id = proxy_log_id = api.create_proxy_log(data)
        try:
            self.client_channel.send(wr('Connecting %s@%s:%s ... ' % (system_user.username, asset.ip, asset.port)))
            ssh.connect(hostname=asset.ip, port=asset.port, username=system_user.username,
                        password=password, pkey=private_key, look_for_keys=False,
                        allow_agent=True, compress=True, timeout=timeout)

        except (paramiko.AuthenticationException, paramiko.ssh_exception.SSHException):
            msg = 'Connect backend server %s failed: %s' % (asset.ip, 'Auth failed')
            logger.warning(msg)
            failed = True

        except socket.error:
            msg = 'Connect backend server %s failed: %s' % (asset.ip, 'Timeout')
            logger.warning(msg)
            failed = True
        else:
            msg = 'Connect backend server %(username)s@%(host)s:%(port)s successfully' % {
                       'username': system_user.username,
                       'host': asset.ip,
                       'port': asset.port}
            failed = False
            logger.info(msg)

        if failed:
            self.client_channel.send(wr(warning(msg+'\r\n')))
            data = Dict({
                "proxy_log_id": proxy_log_id,
                "date_finished": datetime.datetime.utcnow(),
                "was_failed": 1
            })
            api.finish_proxy_log(data)
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

            if request.meta.change_channel_size_event.is_set():
                request.meta.change_channel_size_event.clear()
                backend_channel.resize_pty(width=request.meta.channel_width,
                                           height=request.meta.channel.channel_height)

            if client_channel in r:
                # Get output of the command
                self.get_output()

                client_data = client_channel.recv(1024)
                self.in_input_mode = True
                self.is_first_input = False

                # Get command
                self.get_input(client_data)

                if len(client_data) == 0:
                    print(request.meta)
                    logger.info('Logout from ssh server %(host)s: %(username)s' % {
                        'host': request.meta.addr[0],
                        'username': request.meta.username,
                    })
                    break
                backend_channel.send(client_data)

            if backend_channel in r:
                backend_data = backend_channel.recv(1024)
                if len(backend_data) == 0:
                    client_channel.send(wr('Disconnect from %s' % backend_channel.host))
                    logger.info('Logout from backend server %(host)s: %(username)s' % {
                        'host': backend_channel.host,
                        'username': backend_channel.username,
                    })
                    break
                if not self.is_first_input:
                    self.__class__.output_data += backend_data
                client_channel.send(backend_data)
        data = Dict({
                "proxy_log_id": request.meta.proxy_log_id,
                "date_finished": datetime.datetime.utcnow(),
                })
        api.finish_proxy_log(data)


class InteractiveServer(object):
    """Hi, This is a interactive server, show a navigation, accept user input,
    and do [proxy to backend server, execute command, upload file, or other interactively]
    """

    SPECIAL_CHAR = {'\x08': '\x08\x1b[K', '\x7f': '\x08\x1b[K'}

    def __init__(self, client_channel):
        self.backend_server = None
        self.backend_channel = None
        self.client_channel = client_channel
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
        0) 输入 \033[32mQ/q\033[0m 退出.\r\n""" % request.meta.username
        client_channel.send(msg)

        # client_channel.send('\r\n\r\n\t\tWelcome to use Jumpserver open source system !\r\n\r\n')
        # client_channel.send('If you find some bug please contact us <ibuler@qq.com>\r\n')
        # client_channel.send('See more at https://www.jumpserver.org\r\n\r\n')

    def input(self, prompt='Opt> '):
        """Make a prompt let user input, and get user input content"""

        input_ = b''
        parser = TtyIOParser(request.meta.channel_width, request.meta.channel_height)
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
        self.asset_groups = api.get_user_asset_groups_granted(request.meta.user)
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
                self.search_result = api.get_user_asset_group_assets(request.meta.user, asset_group.id)
                self.display_search_result()
                self.dispatch(twice=True)

        self.client_channel.send(wr(warning('No asset group match, please input again')))

    def display_search_result(self):
        if not self.assets:
            self.assets = api.get_user_assets_granted(request.meta.user)
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
            request.meta.asset = asset = self.search_result[0]
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
            request.meta.system_user = system_user
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
            request.meta.client.close()
            return

        self.display_banner()
        while True:
            try:
                self.dispatch()
            except socket.error:
                self.logout()
                break

    def logout(self):
        logger.info('Logout from jumpserver %(host)s: %(username)s' % {
            'host': request.meta.addr[0],
            'username': request.meta.username,
        })
        if request.meta.get('proxy_log_id', ''):
            data = Dict({
                'proxy_log_id': request.meta.proxy_log_id,
                'date_finished': datetime.datetime.utcnow(),
            })
            api.finish_proxy_log(data)
        self.client_channel.close()
        del self


class JumpServer(object):
    requests = []

    def __init__(self):
        self.listen_host = CONFIG.SSH_HOST
        self.listen_port = CONFIG.SSH_PORT
        self.version = '0.3.3'
        self.sock = None
        self.name = CONFIG.NAME
        self.terminal_id = ''

    def auth(self):
        while True:
            result, content = api.terminal_auth()
            if result:
                self.terminal_id = content
                break
            else:
                logger.warning('Terminal auth failed: %s' % content)
                time.sleep(10)

    def heatbeat(self):
        def _keep():
            while True:
                result = api.terminal_heatbeat()
                if not result:
                    logger.warning('Terminal heatbeat failed')
                time.sleep(CONFIG.TERMINAL_HEATBEAT_INTERVAL)

        thread = threading.Thread(target=_keep, args=())
        thread.daemon = True
        thread.start()

    @staticmethod
    def handle_ssh_request(client, addr):
        logger.info("Get ssh request from %(host)s:%(port)s" % {
            'host': addr[0],
            'port': addr[1],
        })
        request.meta = Dict({})
        request.meta.client = client
        request.meta.addr = addr
        transport = paramiko.Transport(client, gss_kex=False)
        # transport.set_gss_host(socket.getfqdn(""))
        try:
            transport.load_server_moduli()
        except:
            logger.warning('Failed to load moduli -- gex will be unsupported.')
            raise

        transport.add_server_key(SSHInterface.get_host_key())
        ssh_interface = SSHInterface()

        try:
            transport.start_server(server=ssh_interface)
        except paramiko.SSHException:
            logger.warning('SSH negotiation failed.')

        request.client_channel = client_channel = transport.accept(20)
        if client_channel is None:
            logger.warning('No ssh channel get.')
            return None

        # ssh_interface.shell_event.wait(1)
        # ssh_interface.command_event.wait(1)
        if ssh_interface.shell_event.is_set():
            logger.info('Client asked for a shell.')
            InteractiveServer(client_channel).run()

        if ssh_interface.command_event.is_set():
            client_channel.send(wr(warning('We are not support execute command now')))
            client_channel.close()
            sys.exit(1)

        while True:
            if getattr(request.meta, 'user'):
                break
            else:
                time.sleep(0.2)
        return client_channel

    def run_forever(self):
        self.sock = sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.listen_host, self.listen_port))
        sock.listen(5)

        print(time.ctime())
        print('Jumpserver terminal version %s, more see https://www.jumpserver.org' % self.version)
        print('Starting ssh server at %(host)s:%(port)s' % {'host': self.listen_host, 'port': self.listen_port})
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


if __name__ == '__main__':
    server = JumpServer()
    try:
        server.auth()
        server.heatbeat()
        server.run_forever()
    except KeyboardInterrupt:
        server.close()
        sys.exit(1)

