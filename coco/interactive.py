#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import socket
import threading
import os

from . import char
from .utils import wrap_with_line_feed as wr, wrap_with_title as title, \
    wrap_with_warning as warning, is_obj_attr_has, is_obj_attr_eq, \
    sort_assets, ugettext as _, get_logger, net_input, format_with_zh, \
    item_max_length, size_of_str_with_zh
from .ctx import current_app, app_service
from .proxy import ProxyServer

logger = get_logger(__file__)


class InteractiveServer:
    _sentinel = object()

    def __init__(self, client):
        self.client = client
        self.request = client.request
        self.assets = None
        self._search_result = None
        self.nodes = None
        self.get_user_assets_async()
        self.get_user_nodes_async()

    @property
    def search_result(self):
        if self._search_result:
            return self._search_result
        else:
            return []

    @search_result.setter
    def search_result(self, value):
        if not value:
            self._search_result = value
            return
        value = self.filter_system_users(value)
        self._search_result = value

    def display_banner(self):
        self.client.send(char.CLEAR_CHAR)
        logo_path = os.path.join(current_app.root_path, "logo.txt")
        if os.path.isfile(logo_path):
            with open(logo_path, 'rb') as f:
                for i in f:
                    if i.decode('utf-8').startswith('#'):
                        continue
                    self.client.send(i.decode('utf-8').replace('\n', '\r\n'))

        banner = _("""\n {title}   {user}, 欢迎使用Jumpserver开源跳板机系统  {end}\r\n\r
    1) 输入 {green}ID{end} 直接登录 或 输入{green}部分 IP,主机名,备注{end} 进行搜索登录(如果唯一).\r
    2) 输入 {green}/{end} + {green}IP, 主机名{end} or {green}备注 {end}搜索. 如: /ip\r
    3) 输入 {green}p{end} 显示您有权限的主机.\r
    4) 输入 {green}g{end} 显示您有权限的节点\r
    5) 输入 {green}g{end} + {green}组ID{end} 显示节点下主机. 如: g1\r
    6) 输入 {green}h{end} 帮助.\r
    0) 输入 {green}q{end} 退出.\r\n""").format(
            title="\033[1;32m", green="\033[32m",
            end="\033[0m", user=self.client.user
        )
        self.client.send(banner)

    def dispatch(self, opt):
        if opt is None:
            return self._sentinel
        elif opt.startswith("/"):
            self.search_and_display(opt.lstrip("/"))
        elif opt in ['p', 'P', '']:
            self.display_assets()
        elif opt in ['g', 'G']:
            self.display_nodes()
        elif opt.startswith("g") and opt.lstrip("g").isdigit():
            self.display_node_assets(int(opt.lstrip("g")))
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
        if q in ('', None):
            result = self.assets
        # 用户输入的是数字，可能想使用id唯一键搜索
        elif q.isdigit() and self.search_result and \
                len(self.search_result) >= int(q):
            result = [self.search_result[int(q) - 1]]

        # 全匹配到则直接返回全匹配的
        if len(result) == 0:
            _result = [asset for asset in self.assets
                       if is_obj_attr_eq(asset, q)]
            if len(_result) == 1:
                result = _result

        # 最后模糊匹配
        if len(result) == 0:
            result = [asset for asset in self.assets
                      if is_obj_attr_has(asset, q)]

        self.search_result = result

    def display_assets(self):
        """
        Display user all assets
        :return:
        """
        self.search_and_display('')

    def display_nodes(self):
        if self.nodes is None:
            self.get_user_nodes()

        if len(self.nodes) == 0:
            self.client.send(warning(_("无")))
            return

        id_length = max(len(str(len(self.nodes))), 5)
        name_length = item_max_length(self.nodes, 15, key=lambda x: x.name)
        amount_length = item_max_length(self.nodes, 10,
                                        key=lambda x: x.assets_amount)
        size_list = [id_length, name_length, amount_length]
        fake_data = ['ID', _("Name"), _("Assets")]
        header_without_comment = format_with_zh(size_list, *fake_data)
        comment_length = max(
            self.request.meta["width"] -
            size_of_str_with_zh(header_without_comment) - 1,
            2
        )
        size_list.append(comment_length)
        fake_data.append(_("Comment"))

        self.client.send(title(format_with_zh(size_list, *fake_data)))
        for index, group in enumerate(self.nodes, 1):
            data = [index, group.name, group.assets_amount, group.comment]
            self.client.send(wr(format_with_zh(size_list, *data)))
        self.client.send(wr(_("总共: {}").format(len(self.nodes)), before=1))

    def display_node_assets(self, _id):
        if _id > len(self.nodes) or _id <= 0:
            self.client.send(wr(warning("没有匹配分组，请重新输入")))
            self.display_nodes()
            return

        self.search_result = self.nodes[_id - 1].assets_granted
        self.display_search_result()

    def display_search_result(self):
        sort_by = current_app.config["ASSET_LIST_SORT_BY"]
        self.search_result = sort_assets(self.search_result, sort_by)
        fake_data = [_("ID"), _("Hostname"), _("IP"), _("LoginAs")]
        id_length = max(len(str(len(self.search_result))), 4)
        hostname_length = item_max_length(self.search_result, 15,
                                          key=lambda x: x.hostname)
        sysuser_length = item_max_length(self.search_result,
                                         key=lambda x: x.system_users_name_list)
        size_list = [id_length, hostname_length, 16, sysuser_length]
        header_without_comment = format_with_zh(size_list, *fake_data)
        comment_length = max(
            self.request.meta["width"] -
            size_of_str_with_zh(header_without_comment) - 1,
            2
        )
        size_list.append(comment_length)
        fake_data.append(_("Comment"))
        self.client.send(wr(title(format_with_zh(size_list, *fake_data))))
        for index, asset in enumerate(self.search_result, 1):
            data = [
                index, asset.hostname, asset.ip,
                asset.system_users_name_list, asset.comment
            ]
            self.client.send(wr(format_with_zh(size_list, *data)))
        self.client.send(wr(_("总共: {} 匹配: {}").format(
            len(self.assets), len(self.search_result)), before=1)
        )

    def search_and_display(self, q):
        self.search_assets(q)
        self.display_search_result()

    def get_user_nodes(self):
        self.nodes = app_service.get_user_asset_groups(self.client.user)

    def get_user_nodes_async(self):
        thread = threading.Thread(target=self.get_user_nodes)
        thread.start()

    @staticmethod
    def filter_system_users(assets):
        for asset in assets:
            system_users_granted = asset.system_users_granted
            high_priority = max([s.priority for s in system_users_granted]) \
                if system_users_granted else 1
            system_users_cleaned = [s for s in system_users_granted
                                    if s.priority == high_priority]
            asset.system_users_granted = system_users_cleaned
        return assets

    def get_user_assets(self):
        self.assets = app_service.get_user_assets(self.client.user)
        logger.debug("Get user {} assets total: {}".format(
            self.client.user, len(self.assets))
        )

    def get_user_assets_async(self):
        thread = threading.Thread(target=self.get_user_assets)
        thread.start()

    def choose_system_user(self, system_users):
        if len(system_users) == 1:
            return system_users[0]
        elif len(system_users) == 0:
            return None

        while True:
            self.client.send(wr(_("选择一个登录: "), after=1))
            self.display_system_users(system_users)
            opt = net_input(self.client, prompt="ID> ")
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
            self.search_result = None
            if asset.platform == "Windows":
                self.client.send(warning(
                    _("终端不支持登录windows, 请使用web terminal访问"))
                )
                return
            self.proxy(asset)
        else:
            self.display_search_result()

    def proxy(self, asset):
        system_user = self.choose_system_user(asset.system_users_granted)
        if system_user is None:
            self.client.send(_("没有系统用户"))
            return
        forwarder = ProxyServer(self.client, login_from='ST')
        forwarder.proxy(asset, system_user)

    def interact(self):
        self.display_banner()
        while True:
            try:
                opt = net_input(self.client, prompt='Opt> ', before=1)
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
        current_app.remove_client(self.client)

    # def __del__(self):
    #     print("GC: Interactive class been gc")
