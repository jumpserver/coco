#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import socket
import threading
import os

from . import char
from .config import config
from .utils import wrap_with_line_feed as wr, wrap_with_title as title, \
    wrap_with_warning as warning, is_obj_attr_has, is_obj_attr_eq, \
    sort_assets, ugettext as _, get_logger, net_input, format_with_zh, \
    item_max_length, size_of_str_with_zh, switch_lang
from .service import app_service
from .proxy import ProxyServer

logger = get_logger(__file__)


class InteractiveServer:
    _sentinel = object()

    def __init__(self, client):
        self.client = client
        self.assets = None
        self.closed = False
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

    def display_logo(self):
        logo_path = os.path.join(config['ROOT_PATH'], "logo.txt")
        if not os.path.isfile(logo_path):
            return
        with open(logo_path, 'rb') as f:
            for i in f:
                if i.decode('utf-8').startswith('#'):
                    continue
                self.client.send(i.decode('utf-8').replace('\n', '\r\n'))

    def display_banner(self):
        self.client.send(char.CLEAR_CHAR)
        self.display_logo()
        header = _("\n{T}{T}{title} {user}, Welcome to use Jumpserver open source fortress system {end}{R}{R}")
        menus = [
            _("{T}1) Enter {green}ID{end} directly login or enter {green}part IP, Hostname, Comment{end} to search login(if unique).{R}"),
            _("{T}2) Enter {green}/{end} + {green}IP, Hostname{end} or {green}Comment {end} search, such as: /ip.{R}"),
            _("{T}3) Enter {green}p{end} to display the host you have permission.{R}"),
            _("{T}4) Enter {green}g{end} to display the node that you have permission.{R}"),
            _("{T}5) Enter {green}g{end} + {green}Group ID{end} to display the host under the node, such as g1.{R}"),
            _("{T}6) Enter {green}s{end} Chinese-english switch.{R}"),
            _("{T}7) Enter {green}h{end} help.{R}"),
            _("{T}0) Enter {green}q{end} exit.{R}")
        ]
        self.client.send(header.format(
            title="\033[1;32m", user=self.client.user, end="\033[0m",
            T='\t', R='\r\n\r'
        ))
        for menu in menus:
            self.client.send(menu.format(
                green="\033[32m", end="\033[0m",
                T='\t', R='\r\n\r'
            ))

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
        elif opt in ['s', 'S']:
            switch_lang()
            self.display_banner()
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
            self.client.send(warning(_("No")))
            return

        id_length = max(len(str(len(self.nodes))), 5)
        name_length = item_max_length(self.nodes, 15, key=lambda x: x.name)
        amount_length = item_max_length(self.nodes, 10, key=lambda x: x.assets_amount)
        size_list = [id_length, name_length, amount_length]
        fake_data = ['ID', _("Name"), _("Assets")]

        self.client.send(wr(title(format_with_zh(size_list, *fake_data))))
        for index, node in enumerate(self.nodes, 1):
            data = [index, node.name, node.assets_amount]
            self.client.send(wr(format_with_zh(size_list, *data)))
        self.client.send(wr(_("Total: {}").format(len(self.nodes)), before=1))

    def display_node_assets(self, _id):
        if self.nodes is None:
            self.get_user_nodes()
        if _id > len(self.nodes) or _id <= 0:
            msg = wr(warning(_("There is no matched node, please re-enter")))
            self.client.send(msg)
            self.display_nodes()
            return

        self.search_result = self.nodes[_id - 1].assets_granted
        self.display_search_result()

    def display_search_result(self):
        sort_by = config["ASSET_LIST_SORT_BY"]
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
            self.client.request.meta["width"] -
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
        self.client.send(wr(_("Total: {} Match: {}").format(
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
            self.client.send(wr(_("Select a login:: "), after=1))
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
                    _("Terminal does not support login Windows, "
                      "please use web terminal to access"))
                )
                return
            self.proxy(asset)
        else:
            self.display_search_result()

    def proxy(self, asset):
        system_user = self.choose_system_user(asset.system_users_granted)
        if system_user is None:
            self.client.send(_("No system user"))
            return
        forwarder = ProxyServer(self.client, asset, system_user)
        forwarder.proxy()

    def interact(self):
        self.display_banner()
        while not self.closed:
            try:
                opt = net_input(self.client, prompt='Opt> ', before=1)
                rv = self.dispatch(opt)
                if rv is self._sentinel:
                    break
            except socket.error as e:
                logger.debug("Socket error: {}".format(e))
                break
        self.close()

    def interact_async(self):
        thread = threading.Thread(target=self.interact)
        thread.daemon = True
        thread.start()

    def close(self):
        logger.debug("Interactive server server close: {}".format(self))
        self.closed = True
        # current_app.remove_client(self.client)

    # def __del__(self):
    #     print("GC: Interactive class been gc")
