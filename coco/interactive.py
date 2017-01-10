# ~*~ coding: utf-8 ~*~

import sys
import select
import re
import socket
import logging
import datetime

from . import wr, primary, info, warning, title, cml
from .proxy import ProxyServer
from .globals import request, g
from .utils import TtyIOParser

logger = logging.getLogger(__file__)


class InteractiveServer(object):
    """Hi, This is a interactive server, show a navigation, accept user input,
    and do [proxy to backend server, execute command, upload file, or other interactively]
    """

    SPECIAL_CHAR = {'\x08': '\x08\x1b[K', '\x7f': '\x08\x1b[K'}
    ENTER_CHAR = ['\r', '\n', '\r\n']
    CLEAR_CHAR = '\x1b[H\x1b[2J'
    BELL_CHAR = b'\x07'

    def __init__(self, app):
        self.app = app
        self.app_service = app.app_service
        self.backend_server = None
        self.backend_channel = None
        self.assets = None  # self.get_user_assets_granted()
        self.asset_groups = None  # self.get_user_asset_groups_granted()
        self.search_result = []

    def display_banner(self):
        g.client_channel.send(self.CLEAR_CHAR)
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

        g.client_channel.send(msg)

        # g.client_channel.send('\r\n\r\n\t\tWelcome to use Jumpserver open source system !\r\n\r\n')
        # g.client_channel.send('If you find some bug please contact us <ibuler@qq.com>\r\n')
        # g.client_channel.send('See more at https://www.jumpserver.org\r\n\r\n')

    def get_input(self, prompt='Opt> '):
        """Make a prompt let user input, and get user input content"""

        input_ = b''
        parser = TtyIOParser(request.win_width, request.win_height)
        g.client_channel.send(wr(prompt, before=1, after=0))
        while True:
            r, w, x = select.select([g.client_channel], [], [])
            if g.client_channel in r:
                data = g.client_channel.recv(1024)

                if data in self.__class__.SPECIAL_CHAR:
                    # If input words less than 0, should send 'BELL'
                    if len(parser.parse_input(input_)) > 0:
                        data = self.__class__.SPECIAL_CHAR[data]
                        input_ += data
                    else:
                        data = self.BELL_CHAR
                    g.client_channel.send(data)
                    continue

                # If user type ENTER we should get user input
                if data in self.ENTER_CHAR:
                    g.client_channel.send(wr('', after=2))
                    option = parser.parse_input(input_)
                    return option.strip()
                else:
                    g.client_channel.send(data)
                    input_ += data

    def dispatch(self, twice=False):
        option = self.get_input()
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
        self.asset_groups = g.user_service.get_user_asset_groups_granted()
        name_max_length = cml([asset_group.name for asset_group in self.asset_groups], max_length=20)
        comment_max_length = cml([asset_group.comment for asset_group in self.asset_groups], max_length=30)
        line = '[%-3s] %-' + str(name_max_length) + 's %-6s  %-' + str(comment_max_length) + 's'
        g.client_channel.send(wr(title(line % ('ID', 'Name', 'Assets', 'Comment'))))
        for index, asset_group in enumerate(self.asset_groups):
            g.client_channel.send(wr(line % (index, asset_group.name,
                                           asset_group.assets_amount,
                                           asset_group.comment[:comment_max_length])))
        g.client_channel.send(wr(''))

    def display_asset_group_asset(self, option):
        match = re.match(r'g(\d+)', option)
        if match:
            index = match.groups()[0]

            if index.isdigit() and len(self.asset_groups) > int(index):
                asset_group = self.asset_groups[int(index)]
                self.search_result = g.user_service.get_user_asset_group_assets(asset_group.id)
                self.display_search_result()
                self.dispatch(twice=True)

        g.client_channel.send(wr(warning('No asset group match, please input again')))

    def display_search_result(self):
        if self.assets is None:
            self.assets = g.user_service.get_my_assets()
        if not self.search_result:
            self.search_result = self.assets

        hostname_max_length = cml([asset.hostname for asset in self.search_result])
        line = '[%-4s] %-16s %-5s %-' + str(hostname_max_length) + 's %-10s %s'
        g.client_channel.send(wr(title(line % ('ID', 'IP', 'Port', 'Hostname', 'Username', 'Comment'))))

        for index, asset in enumerate(self.search_result):
            system_users = '[' + ', '.join([system_user.username for system_user in asset.system_users]) + ']'
            g.client_channel.send(wr(line % (index, asset.ip, asset.port, asset.hostname,
                                             system_users, asset.comment)))
        g.client_channel.send(wr(''))

    def search_and_display(self, option):
        self.search_assets(option=option)
        self.display_search_result()

    def choose_system_user(self, system_users):
        while True:
            for index, system_user in enumerate(system_users):
                g.client_channel.send(wr('[%s] %s' % (index, system_user.username)))

            option = self.get_input(prompt='System user> ')
            if option.isdigit() and int(option) < len(system_users):
                system_user = system_users[int(option)]
                return system_user
            elif option in ['q', 'Q']:
                return None
            else:
                g.client_channel.send(wr(warning('No system user match, please input again')))

    def search_and_proxy(self, option, from_result=False):
        self.search_assets(option=option, from_result=from_result)
        if len(self.search_result) == 1:
            request.asset = asset = self.search_result[0]
            if len(asset.system_users) == 1:
                system_user = asset.system_users[0]
            else:
                g.client_channel.send(wr(primary('More than one system user granted, select one')))
                system_user = self.choose_system_user(asset.system_users)
                print(system_user)
                if system_user is None:
                    return self.dispatch()

            request.system_user = system_user
            self.return_to_proxy(asset, system_user)
        elif len(self.search_result) == 0:
            g.client_channel.send(wr(warning('No asset match, please input again')))
            return self.dispatch()
        else:
            g.client_channel.send(wr(primary('Search result is not unique, select below or search again'), after=2))
            self.display_search_result()
            self.dispatch(twice=True)

    def return_to_proxy(self, asset, system_user):
        proxy_server = ProxyServer(self.app, asset, system_user)
        proxy_server.proxy()

    def run(self):
        if g.client_channel is None:
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
            'host': request.environ['REMOTE_ADDR'],
            'username': request.user.username,
        })
        # if request.get('proxy_log_id', ''):
        #     data = {
        #         'proxy_log_id': request.proxy_log_id,
        #         'date_finished': datetime.datetime.utcnow(),
        #     }
        #  api.finish_proxy_log(data)
        g.client_channel.close()
        del self


