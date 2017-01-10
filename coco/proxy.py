# ~*~ coding: utf-8 ~*~

import re
import logging
import datetime
import socket
import select

import paramiko

from . import wr, warning
from .globals import request, g
from .utils import TtyIOParser


logger = logging.getLogger(__file__)


class ProxyServer(object):
    """
    We are using this class proxy client channel (user) with backend channel

    When receive client input command, send to backend ssh channel
    and when receive output of command from backend, send to client

    We also record the command and result to database for audit

    """
    output_data = b''
    history = {}
    ENTER_CHAR = ['\r', '\n', '\r\n']

    def __init__(self, app, asset, system_user):
        self.app = app
        self.asset = asset
        self.system_user = system_user
        self.app_service = app.app_service
        self.backend_channel = None
        self.ssh = None
        # Whether the terminal in input mode or output mode
        self.in_input_mode = True
        # If is first input, will clear the output data: ssh banner and PS1
        self.is_first_input = True
        # This ssh session command serial no
        self.cmd_no = 0
        self.in_vim_mode = False
        self.vim_pattern = re.compile(r'\x1b\[\?1049', re.X)
        self.input = ''
        self.output = ''

    def is_finish_input(self, s):
        for char in s:
            if char in self.ENTER_CHAR:
                return True
        return False

    def get_output(self):
        if self.in_input_mode is False:
            parser = TtyIOParser(width=request.win_width,
                                 height=request.win_height)
            self.output = parser.parse_output(self.__class__.output_data)
            print('>' * 10 + 'Output' + '<' * 10)
            print(self.output)
            print('>' * 10 + 'End output' + '<' * 10)
            if self.input:
                # task.create_command_log.delay(task, self.no, self.input, self.output,
                #                               request.proxy_log_id, datetime.datetime.utcnow())
                self.cmd_no += 1

    def get_input(self, client_data):
        if self.is_finish_input(client_data):
            vim_match = self.vim_pattern.findall(self.__class__.output_data)
            if vim_match:
                if self.in_vim_mode or len(vim_match) == 2:
                    self.in_vim_mode = False
                else:
                    self.in_vim_mode = True

            if not self.in_vim_mode:
                parser = TtyIOParser(width=request.win_width,
                                     height=request.win_height)
                self.input = parser.parse_input(self.__class__.output_data)
                print('#' * 10 + 'Command' + '#' * 10)
                print(self.input)
                print('#' * 10 + 'End command' + '#' * 10)

            self.in_input_mode = False

    # Todo: App check user permission
    def validate_user_permission(self, asset, system_user):
        #assets = g.user_service.get_user_assets_granted(request.user)
        #for a in assets:
        #    if asset.id == a.id:
        #        for s in asset.system_users:
        #            if system_user.id == s.id:
        #                return True
        return True

    def get_asset_auth(self, system_user):
        return self.app_service.get_system_user_auth_info(system_user)

    def connect(self, term=b'xterm', width=80, height=24, timeout=10):
        asset = self.asset
        system_user = self.system_user
        if not self.validate_user_permission(asset, system_user):
            logger.warning('User %s have no permission connect %s with %s' % (request.user.username,
                                                                              asset.ip, system_user.username))
            return None
        self.ssh = ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        password, private_key = self.get_asset_auth(self.system_user)
        data = {"username": request.user.username, "name": request.user.name,
                "hostname": self.asset.hostname, "ip": self.asset.ip,
                "system_user": self.system_user.username,  "login_type": "S",
                "date_start": datetime.datetime.utcnow(), "was_failed": 0}
        # request.proxy_log_id = proxy_log_id = api.create_proxy_log(data)
        try:
            g.client_channel.send(wr('Connecting %s@%s:%s ... ' % (system_user.username, asset.ip, asset.port)))
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
            g.client_channel.send(wr(warning(msg+'\r\n')))
            data = {
                # "proxy_log_id": proxy_log_id,
                "proxy_log_id": 1,
                "date_finished": datetime.datetime.utcnow(),
                "was_failed": 1
            }
            # api.finish_proxy_log(data)
            return None

        self.backend_channel = channel = ssh.invoke_shell(term=term, width=width, height=height)
        channel.settimeout(100)
        channel.host = asset.ip
        channel.port = asset.port
        channel.username = system_user.username
        return channel

    def proxy(self):
        self.backend_channel = backend_channel = self.connect()

        if backend_channel is None:
            return

        while True:
            r, w, x = select.select([g.client_channel, backend_channel], [], [])

            if request.change_win_size_event.is_set():
                request.change_win_size_event.clear()
                backend_channel.resize_pty(width=request.win_width,
                                           height=request.win_height)

            if g.client_channel in r:
                # Get output of the command
                self.get_output()

                client_data = g.client_channel.recv(1024)
                self.in_input_mode = True
                self.is_first_input = False

                # Get command
                self.get_input(client_data)

                if len(client_data) == 0:
                    logger.info('Logout from ssh server %(host)s: %(username)s' % {
                        'host': request.environ['REMOTE_ADDR'],
                        'username': request.user.username,
                    })
                    break
                backend_channel.send(client_data)

            if backend_channel in r:
                backend_data = backend_channel.recv(1024)
                if len(backend_data) == 0:
                    g.client_channel.send(wr('Disconnect from %s' % backend_channel.host))
                    logger.info('Logout from backend server %(host)s: %(username)s' % {
                        'host': backend_channel.host,
                        'username': backend_channel.username,
                    })
                    break
                if not self.is_first_input:
                    self.__class__.output_data += backend_data
                g.client_channel.send(backend_data)
        # data = {
        #         "proxy_log_id": request.proxy_log_id,
        #         "date_finished": datetime.datetime.utcnow(),
        #         }
        # api.finish_proxy_log(data)
