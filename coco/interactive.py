# ~*~ coding: utf-8 ~*~

from __future__ import unicode_literals

import sys
import select
import re
import socket
import threading
import logging

from .proxy import ProxyServer
from .globals import request
from jms.utils import TtyIOParser
from .utils import system_user_max_length, max_length
from jms.utils import wrap_with_line_feed as wr, wrap_with_primary as primary,\
    wrap_with_warning as warning, wrap_with_title as title


logger = logging.getLogger(__file__)


class InteractiveServer(object):
    """Hi, This is a interactive server, show a navigation, accept user input,
    and do [proxy to backend server, execute command, upload file, or other interactively]
    """

    BACKSPACE_CHAR = {b'\x08': b'\x08\x1b[K', b'\x7f': b'\x08\x1b[K'}
    ENTER_CHAR = [b'\r', b'\n', b'\r\n']
    UNSUPPORTED_CHAR = {b'\x15': 'Ctrl-U', b'\x0c': 'Ctrl-L',
                        b'\x05': 'Ctrl-E'}
    CLEAR_CHAR = b'\x1b[H\x1b[2J'
    BELL_CHAR = b'\x07'

    def __init__(self, app, user_service, client_channel):
        self.app = app
        self.user_service = user_service
        self.service = app.service
        self.backend_server = None
        self.client_channel = client_channel
        self.backend_channel = None
        self.user = request.user
        self.assets = self.get_my_assets()
        self.asset_groups = self.get_my_asset_groups()
        self.search_result = []

    def display_banner(self):
        self.client_channel.send(self.CLEAR_CHAR)
        msg = u"""\n\033[1;32m  %s, 欢迎使用Jumpserver开源跳板机系统  \033[0m\r\n\r
        1) 输入 \033[32mID\033[0m 直接登录 或 输入\033[32m部分 IP,主机名,备注\033[0m 进行搜索登录(如果唯一).\r
        2) 输入 \033[32m/\033[0m + \033[32mIP, 主机名 or 备注 \033[0m搜索. 如: /ip\r
        3) 输入 \033[32mP/p\033[0m 显示您有权限的主机.\r
        4) 输入 \033[32mG/g\033[0m 显示您有权限的主机组.\r
        5) 输入 \033[32mG/g\033[0m\033[0m + \033[32m组ID\033[0m 显示该组下主机. 如: g1\r
        6) 输入 \033[32mE/e\033[0m 批量执行命令.(未完成)\r
        7) 输入 \033[32mU/u\033[0m 批量上传文件.(未完成)\r
        8) 输入 \033[32mD/d\033[0m 批量下载文件.(未完成)\r
        9) 输入 \033[32mH/h\033[0m 帮助.\r
        0) 输入 \033[32mQ/q\033[0m 退出.\r\n""" % request.user.username

        self.client_channel.send(msg)

    def get_input(self, prompt='Opt> '):
        """实现了一个ssh input, 提示用户输入, 获取并返回"""
        input_data = []
        parser = TtyIOParser(request.win_width, request.win_height)
        self.client_channel.send(wr(prompt, before=1, after=0))
        while True:
            r, w, x = select.select([self.client_channel], [], [])
            if self.client_channel in r:
                data = self.client_channel.recv(1024)
                if data in self.BACKSPACE_CHAR:
                    # If input words less than 0, should send 'BELL'
                    if len(input_data) > 0:
                        data = self.BACKSPACE_CHAR[data]
                        input_data.pop()
                    else:
                        data = self.BELL_CHAR
                    self.client_channel.send(data)
                    continue

                if data.startswith(b'\x1b') or data in self.UNSUPPORTED_CHAR:
                    self.client_channel.send('')
                    continue

                # handle shell expect
                multi_char_with_enter = False
                if len(data) > 1 and data[-1] in self.ENTER_CHAR:
                    self.client_channel.send(data)
                    input_data.append(data[:-1])
                    multi_char_with_enter = True

                # If user type ENTER we should get user input
                if data in self.ENTER_CHAR or multi_char_with_enter:
                    self.client_channel.send(wr('', after=2))
                    option = parser.parse_input(b''.join(input_data))
                    return option.strip()
                else:
                    self.client_channel.send(data)
                    input_data.append(data)

    def dispatch(self, twice=False):
        """根据用户的输入执行不同的操作
        P, p: 打印用户所有资产
        /: 搜索资产, 支持资产名, ip, 备注等
        G, g: 打印用户有权限的资产组
        g+index: 打印该资产组下的资产
        q: 退出
        h: 打印帮助
        直接搜索登录: 直接输入会搜索, 如果唯一则直接登录资产
        """
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
        """搜索资产
        :param option: 搜索内容
        :param from_result: 是否从上次结果里搜索
        """
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
                ] or [asset for asset in assets
                          if option in asset.ip or
                             option in asset.hostname.lower() or
                             option in asset.comment.lower()
                ]
        else:
            self.search_result = self.assets

    def display_assets(self):
        """打印用户所有资产"""
        self.search_and_display('')

    def get_my_asset_groups(self):
        """获取用户授权的资产组"""
        logger.debug("Start get my asset groups")
        groups = self.user_service.get_my_asset_groups()
        logger.debug("End get my asset groups")
        return groups

    def get_my_assets(self):
        logger.debug("Start get my assets")
        assets = self.user_service.get_my_assets()
        logger.debug("End get my assets")
        return assets

    def display_asset_groups(self):
        """打印授权的资产组"""
        self.asset_groups = self.get_my_asset_groups()
        name_max_length = max_length([asset_group.name for asset_group
                                      in self.asset_groups], max_=20)
        comment_max_length = max_length([asset_group.comment for asset_group
                                         in self.asset_groups], max_=30)
        line = '[%-3s] %-' + str(name_max_length) + 's %-6s  %-' \
               + str(comment_max_length) + 's'
        self.client_channel.send(wr(title(line % ('ID', 'Name', 'Assets', 'Comment'))))
        for index, asset_group in enumerate(self.asset_groups):
            self.client_channel.send(wr(line % (
                index, asset_group.name,
                asset_group.assets_amount,
                asset_group.comment[:comment_max_length])))
        self.client_channel.send(wr(''))

    def display_asset_group_asset(self, option):
        """打印资产组下的资产"""
        match = re.match(r'g(\d+)', option)
        if match:
            index = match.groups()[0]
            if index.isdigit() and len(self.asset_groups) > int(index):
                asset_group = self.asset_groups[int(index)]
                self.search_result = self.user_service.\
                    get_assets_in_group(asset_group.id)
                self.display_search_result()
                self.dispatch(twice=True)
        self.client_channel.send(wr(warning(
            'No asset group match, please input again')))

    def display_search_result(self):
        """打印搜索的结果"""
        if self.assets is None:
            self.assets = self.get_my_assets()
        if not self.search_result:
            self.search_result = self.assets

        hostname_length = max_length([asset.hostname for asset in self.search_result])
        system_user_length = system_user_max_length(self.assets)
        line = '[%-4s] %-16s %-5s %-' + str(hostname_length) + 's %-' + str(system_user_length+2) + 's '
        comment_length = request.win_width-len(line % ((' ',) * 5)) - 5
        line += ('%-' + str(comment_length) + 's')
        self.client_channel.send(wr(title(line % (
            'ID', 'IP', 'Port', 'Hostname', 'Username', 'Comment'))))

        for index, asset in enumerate(self.search_result):
            system_users = '[' + ', '.join(
                [system_user.username for system_user in asset.system_users]) \
                + ']'
            self.client_channel.send(wr(
                line % (index, asset.ip, asset.port, asset.hostname,
                        system_users, asset.comment)))
        self.client_channel.send(wr(''))

    def search_and_display(self, option):
        """搜索并打印资产"""
        self.search_assets(option=option)
        self.display_search_result()

    def choose_system_user(self, system_users):
        """当资产上有多个授权系统用户时, 让用户二次选择"""
        while True:
            for index, system_user in enumerate(system_users):
                self.client_channel.send(wr('[%s] %s' % (index, system_user.username)))

            option = self.get_input(prompt='System user> ')
            if option.isdigit() and int(option) < len(system_users):
                system_user = system_users[int(option)]
                return system_user
            elif option in ['q', 'Q']:
                return None
            else:
                self.client_channel.send(
                    wr(warning('No system user match, please input again')))

    def search_and_proxy(self, option, from_result=False):
        """搜索并登录资产"""
        self.search_assets(option=option, from_result=from_result)
        if len(self.search_result) == 1:
            request.asset = asset = self.search_result[0]
            if len(asset.system_users) == 1:
                system_user = asset.system_users[0]
            else:
                self.client_channel.send(
                    wr(primary('More than one system user granted, select one')))
                system_user = self.choose_system_user(asset.system_users)
                if system_user is None:
                    return self.dispatch()

            request.system_user = system_user
            self.return_to_proxy(asset, system_user)
        elif len(self.search_result) == 0:
            self.client_channel.send(
                wr(warning('No asset match, please input again')))
            return self.dispatch()
        else:
            self.client_channel.send(
                wr(primary('Search result is not unique, '
                           'select below or search again'), after=2))
            self.display_search_result()
            self.dispatch(twice=True)

    def return_to_proxy(self, asset, system_user):
        """开始登录资产, 使用ProxyServer连接到后端资产"""
        stop_event = threading.Event()
        proxy_server = ProxyServer(self.app, self.user, asset, system_user,
                                   self.client_channel, stop_event=stop_event)
        proxy_server.proxy()

    def run(self):
        if self.client_channel is None:
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
        self.client_channel.close()
        del self


