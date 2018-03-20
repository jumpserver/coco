#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import socket
import threading
import weakref
import os

from jms.models import Asset, AssetGroup

from . import char
from .utils import wrap_with_line_feed as wr, wrap_with_title as title, \
    wrap_with_primary as primary, wrap_with_warning as warning, \
    is_obj_attr_has, is_obj_attr_eq, sort_assets, TtyIOParser, \
    ugettext as _, get_logger
from .proxy import ProxyServer

logger = get_logger(__file__)


class InteractiveServer:
    _sentinel = object()

    def __init__(self, app, client):
        self._app = weakref.ref(app)
        self.client = client
        self.request = client.request
        self.assets = None
        self._search_result = None
        self.asset_groups = None
        self.get_user_assets_async()
        self.get_user_asset_groups_async()

    @property
    def app(self):
        return self._app()

    @property
    def search_result(self):
        if self._search_result:
            return self._search_result
        else:
            return []

    @search_result.setter
    def search_result(self, value):
        value = self.filter_system_users(value)
        self._search_result = value

    def display_banner(self):
        self.client.send(char.CLEAR_CHAR)
        logo_path = os.path.join(self.app.root_path, "logo.txt")
        if os.path.isfile(logo_path):
            with open(logo_path, 'rb') as f:
                for i in f:
                    if i.decode('utf-8').startswith('#'):
                        continue
                    self.client.send(i.decode('utf-8').replace('\n', '\r\n'))

        banner = _("""\n {title}   {user}, 欢迎使用Jumpserver开源跳板机系统  {end}\r\n\r
    1) 输入 {green}ID{end} 直接登录 或 输入{green}部分 IP,主机名,备注{end} 进行搜索登录(如果唯一).\r
    2) 输入 {green}/{end} + {green}IP, 主机名{end} or {green}备注 {end}搜索. 如: /ip\r
    3) 输入 {green}P/p{end} 显示您有权限的主机.\r
    4) 输入 {green}G/g{end} 显示您有权限的主机组.\r
    5) 输入 {green}G/g{end} + {green}组ID{end} 显示该组下主机. 如: g1\r
    6) 输入 {green}H/h{end} 帮助.\r
    0) 输入 {green}Q/q{end} 退出.\r\n""").format(
            title="\033[1;32m", green="\033[32m",
            end="\033[0m", user=self.client.user
        )
        self.client.send(banner)

    def get_option(self, prompt='Opt> '):
        """实现了一个ssh input, 提示用户输入, 获取并返回

        :return user input string
        """
        # Todo: 实现自动hostname或IP补全
        input_data = []
        parser = TtyIOParser()
        self.client.send(wr(prompt, before=1, after=0))

        while True:
            data = self.client.recv(10)
            if len(data) == 0:
                self.app.remove_client(self.client)
                break
            # Client input backspace
            if data in char.BACKSPACE_CHAR:
                # If input words less than 0, should send 'BELL'
                if len(input_data) > 0:
                    data = char.BACKSPACE_CHAR[data]
                    input_data.pop()
                else:
                    data = char.BELL_CHAR
                self.client.send(data)
                continue

            if data.startswith(b'\x03'):
                # Ctrl-C
                self.client.send(b'^C\r\nOpt> ')
                input_data = []
                continue
            elif data.startswith(b'\x04'):
                # Ctrl-D
                return 'q'

            # Todo: Move x1b to char
            if data.startswith(b'\x1b') or data in char.UNSUPPORTED_CHAR:
                self.client.send(b'')
                continue

            # handle shell expect
            multi_char_with_enter = False
            if len(data) > 1 and data[-1] in char.ENTER_CHAR_ORDER:
                self.client.send(data)
                input_data.append(data[:-1])
                multi_char_with_enter = True

            # If user type ENTER we should get user input
            if data in char.ENTER_CHAR or multi_char_with_enter:
                self.client.send(wr(b'', after=2))
                option = parser.parse_input(input_data)
                del input_data[:]
                return option.strip()
            else:
                self.client.send(data)
                input_data.append(data)

    def dispatch(self, opt):
        if opt is None:
            return self._sentinel
        elif opt.startswith("/"):
            self.search_and_display(opt.lstrip("/"))
        elif opt in ['p', 'P', '']:
            self.display_assets()
        elif opt in ['g', 'G']:
            self.display_asset_groups()
        elif opt.startswith("g") and opt.lstrip("g").isdigit():
            self.display_group_assets(int(opt.lstrip("g")))
        elif opt in ['q', 'Q', 'exit', 'quit']:
            return self._sentinel
        elif opt in ['h', 'H']:
            self.display_banner()
        else:
            self.search_and_proxy(opt)

    def search_assets(self, q):
        if self.assets is None:
            self.get_user_assets()
        result = []

        # 所有的
        if q == '':
            result = self.assets
        # 用户输入的是数字，可能想使用id唯一键搜索
        elif q.isdigit() and self.search_result and len(self.search_result) >= int(q):
            result = [self.search_result[int(q) - 1]]

        # 全匹配到则直接返回全匹配的
        if len(result) == 0:
            _result = [asset for asset in self.assets if is_obj_attr_eq(asset, q)]
            if len(_result) == 1:
                result = _result

        # 最后模糊匹配
        if len(result) == 0:
            result = [asset for asset in self.assets if is_obj_attr_has(asset, q)]

        self.search_result = result

    def display_assets(self):
        """
        Display user all assets
        :return:
        """
        self.search_and_display('')

    def display_asset_groups(self):
        if self.asset_groups is None:
            self.get_user_asset_groups()

        if len(self.asset_groups) == 0:
            self.client.send(warning(_("无")))
            return

        fake_group = AssetGroup(name=_("Name"), assets_amount=_("Assets"), comment=_("Comment"))
        id_max_length = max(len(str(len(self.asset_groups))), 5)
        name_max_length = max(max([len(group.name) for group in self.asset_groups]), 15)
        amount_max_length = max(len(str(max([group.assets_amount for group in self.asset_groups]))), 10)
        header = '{1:>%d} {0.name:%d} {0.assets_amount:<%s} ' % (id_max_length, name_max_length, amount_max_length)
        comment_length = self.request.meta["width"] - len(header.format(fake_group, id_max_length))
        line = header + '{0.comment:%s}' % (comment_length // 2)  # comment中可能有中文
        header += "{0.comment:%s}" % comment_length
        self.client.send(title(header.format(fake_group, "ID")))
        for index, group in enumerate(self.asset_groups, 1):
            self.client.send(wr(line.format(group, index)))
        self.client.send(wr(_("总共: {}").format(len(self.asset_groups)), before=1))

    def display_group_assets(self, _id):
        if _id > len(self.asset_groups) or _id <= 0:
            self.client.send(wr(warning("没有匹配分组，请重新输入")))
            self.display_asset_groups()
            return

        self.search_result = self.asset_groups[_id - 1].assets_granted
        self.display_search_result()

    def display_search_result(self):
        self.search_result = sort_assets(self.search_result, self.app.config["ASSET_LIST_SORT_BY"])
        fake_asset = Asset(hostname=_("Hostname"), ip=_("IP"), _system_users_name_list=_("LoginAs"),
                           comment=_("Comment"))
        id_max_length = max(len(str(len(self.search_result))), 3)
        hostname_max_length = max(max([len(asset.hostname) for asset in self.search_result + [fake_asset]]), 15)
        sysuser_max_length = max([len(asset.system_users_name_list) for asset in self.search_result + [fake_asset]])
        header = '{1:>%d} {0.hostname:%d} {0.ip:15} {0.system_users_name_list:%d} ' % \
                 (id_max_length, hostname_max_length, sysuser_max_length)
        comment_length = self.request.meta["width"] - len(header.format(fake_asset, id_max_length))
        line = header + '{0.comment:.%d}' % (comment_length // 2)  # comment中可能有中文
        header += '{0.comment:%s}' % comment_length
        self.client.send(wr(title(header.format(fake_asset, "ID"))))
        for index, asset in enumerate(self.search_result, 1):
            self.client.send(wr(line.format(asset, index)))
        self.client.send(wr(_("总共: {} 匹配: {}").format(
            len(self.assets), len(self.search_result)), before=1)
        )

    def search_and_display(self, q):
        self.search_assets(q)
        self.display_search_result()

    def get_user_asset_groups(self):
        self.asset_groups = self.app.service.get_user_asset_groups(self.client.user)

    def get_user_asset_groups_async(self):
        thread = threading.Thread(target=self.get_user_asset_groups)
        thread.start()

    @staticmethod
    def filter_system_users(assets):
        for asset in assets:
            system_users_granted = asset.system_users_granted
            high_priority = max([s.priority for s in system_users_granted]) if system_users_granted else 1
            system_users_cleaned = [s for s in system_users_granted if s.priority == high_priority]
            asset.system_users_granted = system_users_cleaned
        return assets

    def get_user_assets(self):
        self.assets = self.app.service.get_user_assets(self.client.user)
        logger.debug("Get user {} assets total: {}".format(self.client.user, len(self.assets)))

    def get_user_assets_async(self):
        thread = threading.Thread(target=self.get_user_assets)
        thread.start()

    def choose_system_user(self, system_users):
        # highest_priority = max([s.priority for s in system_users])
        # system_users = [s for s in system_users if s == highest_priority]

        if len(system_users) == 1:
            return system_users[0]
        elif len(system_users) == 0:
            return None

        while True:
            self.client.send(wr(_("选择一个登陆: "), after=1))
            self.display_system_users(system_users)
            opt = self.get_option("ID> ")
            if opt.isdigit() and len(system_users) > int(opt):
                return system_users[int(opt)]
            elif opt in ['q', 'Q']:
                return None
            else:
                for system_user in system_users:
                    if system_user.name == opt:
                        return system_user

    def display_system_users(self, system_users):
        for index, system_user in enumerate(system_users):
            self.client.send(wr("{} {}".format(index, system_user.name)))

    def search_and_proxy(self, opt):
        self.search_assets(opt)
        if self.search_result and len(self.search_result) == 1:
            asset = self.search_result[0]
            if asset.platform == "Windows":
                self.client.send(warning(_("终端不支持登录windows, 请使用web terminal访问")))
                return
            self.proxy(asset)
        else:
            self.display_search_result()

    def proxy(self, asset):
        system_user = self.choose_system_user(asset.system_users_granted)
        if system_user is None:
            self.client.send(_("没有系统用户"))
            return
        forwarder = ProxyServer(self.app, self.client)
        forwarder.proxy(asset, system_user)

    def interact(self):
        self.display_banner()
        while True:
            try:
                opt = self.get_option()
                rv = self.dispatch(opt)
                if rv is self._sentinel:
                    break
            except socket.error:
                break
        self.close()

    def interact_async(self):
        thread = threading.Thread(target=self.interact)
        thread.daemon = True
        thread.start()

    def close(self):
        self.app.remove_client(self.client)

    # def __del__(self):
    #     print("GC: Interactive class been gc")
