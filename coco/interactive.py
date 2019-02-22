#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
from __future__ import unicode_literals

import socket
import threading
import os
import math
import time
from treelib import Tree

from . import char
from .conf import config
from .utils import wrap_with_line_feed as wr, wrap_with_title as title, \
    wrap_with_warning as warning, is_obj_attr_has, is_obj_attr_eq, \
    sort_assets, ugettext as _, get_logger, net_input, format_with_zh, \
    item_max_length, size_of_str_with_zh, switch_lang
from .service import app_service
from .proxy import ProxyServer

logger = get_logger(__file__)

PAGE_DOWN = 'down'
PAGE_UP = 'up'
BACK = 'back'
PROXY = 'proxy'


class InteractiveServer:
    _sentinel = object()
    _user_assets_cached = {}

    def __init__(self, client):
        self.client = client
        self.closed = False
        self._results = None
        self.nodes = None
        self.assets = None
        self.get_user_assets_finished = False
        self.page = 1
        self.total_asset_count = 0   # 用户被授权的所有资产数量
        self.total_count = 0  # 分页展示中的资产总数量
        self.node_tree = None  # 授权节点树
        self.load_user_assets_from_cache()
        self.get_user_assets_and_update_async()
        self.get_user_nodes_async()

    @property
    def page_size(self):
        _page_size = config['ASSET_LIST_PAGE_SIZE']
        if _page_size.isdigit():
            return int(_page_size)
        elif _page_size == 'all':
            return self.total_count
        else:
            return self.client.request.meta['height'] - 8

    @property
    def total_pages(self):
        return math.ceil(self.total_count/self.page_size)

    @property
    def need_paging(self):
        return config['ASSET_LIST_PAGE_SIZE'] != 'all'

    @property
    def results(self):
        if self._results:
            return self._results
        else:
            return []

    @results.setter
    def results(self, value):
        self._results = value

    #
    # Display banner
    #

    def display_banner(self):
        default_title = _('Welcome to use Jumpserver open source fortress system')
        header_title = config.get('HEADER_TITLE') or default_title
        self.client.send(char.CLEAR_CHAR)
        self.display_logo()
        header = _("\n{T}{T}{title} {user}, {header_title} {end}{R}{R}")
        menu = [
            _("{T}1) Enter {green}ID{end} directly login or enter {green}part IP, Hostname, Comment{end} to search login(if unique).{R}"),
            _("{T}2) Enter {green}/{end} + {green}IP, Hostname{end} or {green}Comment {end} search, such as: /ip.{R}"),
            _("{T}3) Enter {green}p{end} to display the host you have permission.{R}"),
            _("{T}4) Enter {green}g{end} to display the node that you have permission.{R}"),
            _("{T}5) Enter {green}g{end} + {green}NodeID{end} to display the host under the node, such as g1.{R}"),
            _("{T}6) Enter {green}s{end} Chinese-english switch.{R}"),
            _("{T}7) Enter {green}h{end} help.{R}"),
            _("{T}8) Enter {green}r{end} to refresh your assets and nodes.{R}"),
            _("{T}0) Enter {green}q{end} exit.{R}")
        ]
        self.client.send_unicode(header.format(
            title="\033[1;32m", user=self.client.user,
            header_title=header_title, end="\033[0m",
            T='\t', R='\r\n\r'
        ))
        for item in menu:
            self.client.send_unicode(item.format(
                green="\033[32m", end="\033[0m",
                T='\t', R='\r\n\r'
            ))

    def display_logo(self):
        logo_path = os.path.join(config['ROOT_PATH'], "logo.txt")
        if not os.path.isfile(logo_path):
            return
        with open(logo_path, 'rb') as f:
            for i in f:
                if i.decode('utf-8').startswith('#'):
                    continue
                self.client.send_unicode(i.decode('utf-8').replace('\n', '\r\n'))

    def dispatch(self, opt):
        if opt is None:
            return self._sentinel
        elif opt.startswith("/"):
            self.search_and_display_assets(opt.lstrip("/"))
        elif opt in ['p', 'P', '']:
            self.display_assets()
        elif opt in ['g', 'G']:
            self.display_nodes_as_tree()
        elif opt.startswith("g") and opt.lstrip("g").isdigit():
            self.display_node_assets(int(opt.lstrip("g")))
        elif opt in ['q', 'Q', 'exit', 'quit']:
            return self._sentinel
        elif opt in ['s', 'S']:
            switch_lang()
            self.display_banner()
        elif opt in ['r', 'R']:
            self.refresh_assets_nodes()
            self.display_banner()
        elif opt in ['h', 'H']:
            self.display_banner()
        else:
            self.search_and_proxy_assets(opt)

    #
    # Search assets
    #

    def search_and_display_assets(self, q):
        assets = self.search_assets(q)
        self.display_assets_paging(assets)

    def search_and_proxy_assets(self, opt):
        assets = self.search_assets(opt)
        if assets and len(assets) == 1:
            asset = assets[0]
            if asset.protocol == "rdp" \
                    or asset.platform.lower().startswith("windows"):
                self.client.send_unicode(warning(
                    _("Terminal does not support login rdp, "
                      "please use web terminal to access"))
                )
                return
            self.proxy(asset)
        else:
            self.display_assets_paging(assets)

    def refresh_assets_nodes(self):
        self.get_user_assets_and_update_async()
        self.get_user_nodes_async()

    def wait_until_assets_load(self):
        while self.assets is None and \
                self.get_user_assets_finished is False:
            time.sleep(0.2)

    def search_assets(self, q):
        self.wait_until_assets_load()
        result = []

        # 所有的
        if q in ('', None):
            result = self.assets

        # 用户输入的是数字，可能想使用id唯一键搜索
        elif q.isdigit() and self.results and \
                len(self.results) >= int(q):
            result = [self.results[int(q) - 1]]

        # 全匹配到则直接返回全匹配的
        if len(result) == 0:
            _result = [asset for asset in self.assets if is_obj_attr_eq(asset, q)]
            if len(_result) == 1:
                result = _result

        # 最后模糊匹配
        if len(result) == 0:
            result = [asset for asset in self.assets if is_obj_attr_has(asset, q)]

        return result

    #
    # Display assets
    #

    def display_assets(self):
        self.wait_until_assets_load()
        self.display_assets_paging(self.assets)

    def display_assets_paging(self, assets):
        if len(assets) == 0:
            self.client.send_unicode(wr(_("No Assets"), before=0))
            return
        self.total_count = len(assets)

        action = None
        gen = self._page_generator(assets)
        while True:
            try:
                page, _assets = gen.send(action)
            except StopIteration as e:
                if None not in e.value:
                    page, _assets = e.value
                    self.display_a_page_assets(page, _assets)
                break
            else:
                self.display_a_page_assets(page, _assets)
                self.display_page_bottom_prompt()
                action = self.get_user_action()

    def _page_generator(self, assets):
        start, page = 0, 1
        while not self.client.closed:
            _assets = assets[start:start+self.page_size]
            # 最后一页
            if page == self.total_pages:
                return page, _assets
            # 执行动作
            else:
                action = yield page, _assets

                # 退出
                if action == BACK:
                    break
                # 不分页, 不对页码和下标做更改
                elif not self.need_paging:
                    continue
                # 上一页
                elif action == PAGE_UP:
                    if page <= 1:
                        page = 1
                        start = 0
                    else:
                        page -= 1
                        start -= self.page_size
                # 下一页
                else:
                    page += 1
                    start += len(_assets)
        return None, None

    def display_a_page_assets(self, page, assets):
        self.client.send(char.CLEAR_CHAR)
        self.page = page
        sort_by = config["ASSET_LIST_SORT_BY"]
        self.results = sort_assets(assets, sort_by)
        fake_data = [_("ID"), _("Hostname"), _("IP"), _("LoginAs")]
        id_length = max(len(str(len(self.results))), 4)
        hostname_length = item_max_length(self.results, 15,
                                          key=lambda x: x.hostname)
        sysuser_length = item_max_length(self.results,
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
        self.client.send_unicode(wr(title(format_with_zh(size_list, *fake_data))))
        for index, asset in enumerate(self.results, 1):
            data = [
                index, asset.hostname, asset.ip,
                asset.system_users_name_list, asset.comment
            ]
            self.client.send_unicode(wr(format_with_zh(size_list, *data)))

        self.client.send_unicode(wr(title(
            _("Page: {}, Count: {}, Total Page: {}, Total Count: {}").format(
                self.page, len(self.results), self.total_pages,
                self.total_count)), before=1)
        )

    def display_page_bottom_prompt(self):
        msg = wr(_('Tips: Enter the asset ID and log directly into the asset.'), before=1)
        self.client.send_unicode(msg)
        prompt_page_up = _("Page up: P/p")
        prompt_page_down = _("Page down: Enter|N/n")
        prompt_back = _("BACK: b/q")
        prompts = [prompt_page_up, prompt_page_down, prompt_back]
        prompt = '\t'.join(prompts)
        self.client.send_unicode(wr(prompt, before=1))

    def get_user_action(self):
        opt = net_input(self.client, prompt=':')
        if opt in ('p', 'P'):
            return PAGE_UP
        elif opt in ('b', 'q', None):
            return BACK
        elif opt and opt.isdigit() and self.results and 0 < int(opt) <= len(self.results):
            self.proxy(self.results[int(opt)-1])
            return BACK
        else:
            return PAGE_DOWN

    #
    # Get assets
    #

    def load_user_assets_from_cache(self):
        assets = self.__class__._user_assets_cached.get(
            self.client.user.id
        )
        self.assets = assets
        if assets:
            self.total_asset_count = len(assets)

    def get_user_assets_and_update_async(self):
        thread = threading.Thread(target=self.get_user_assets_and_update)
        thread.start()

    def get_user_assets_and_update(self):
        assets = app_service.get_user_assets(self.client.user)
        assets = self.filter_system_users(assets)
        self.__class__._user_assets_cached[self.client.user.id] = assets
        self.load_user_assets_from_cache()
        self.get_user_assets_finished = True
    #
    # Nodes
    #

    def get_user_nodes_async(self):
        thread = threading.Thread(target=self.get_user_nodes)
        thread.start()

    def get_user_nodes(self):
        nodes = app_service.get_user_asset_groups(self.client.user)
        nodes = sorted(nodes, key=lambda node: node.key)
        self.nodes = self.filter_system_users_of_assets_under_nodes(nodes)
        self._construct_node_tree()

    def filter_system_users_of_assets_under_nodes(self, nodes):
        for node in nodes:
            node.assets_granted = self.filter_system_users(node.assets_granted)
        return nodes

    def _construct_node_tree(self):
        self.node_tree = Tree()
        root = 'ROOT_ALL_ORG_NODE'
        self.node_tree.create_node(tag='', identifier=root, parent=None)
        for index, node in enumerate(self.nodes):
            tag = "{}.{}({})".format(index+1, node.name, node.assets_amount)
            key = node.key
            parent_key = key[:node.key.rfind(':')] or root
            self.node_tree.create_node(tag=tag, identifier=key, data=node, parent=parent_key)

    def display_nodes_as_tree(self):
        if self.nodes is None:
            self.get_user_nodes()

        if not self.nodes:
            self.client.send_unicode(wr(_('No Nodes'), before=0))
            return

        self.node_tree.show(key=lambda node: node.identifier)
        self.client.send_unicode(wr(title(_("Node: [ ID.Name(Asset amount) ]")), before=0))
        self.client.send_unicode(wr(self.node_tree._reader.replace('\n', '\r\n'), before=0))
        prompt = _("Tips: Enter g+NodeID to display the host under the node, such as g1")
        self.client.send_unicode(wr(title(prompt), before=1))

    def display_node_assets(self, _id):
        if self.nodes is None:
            self.get_user_nodes()

        if _id > len(self.nodes) or _id <= 0:
            msg = wr(warning(_("There is no matched node, please re-enter")))
            self.client.send_unicode(msg)
            self.display_nodes_as_tree()
            return

        assets = self.nodes[_id-1].assets_granted
        self.display_assets_paging(assets)

    #
    # System users
    #

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

    def choose_system_user(self, system_users):
        if len(system_users) == 1:
            return system_users[0]
        elif len(system_users) == 0:
            return None

        while True:
            self.client.send_unicode(wr(_("Select a login:: "), after=1))
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
            self.client.send_unicode(wr("{} {}".format(index, system_user.name)))

    #
    # Proxy
    #

    def proxy(self, asset):
        system_user = self.choose_system_user(asset.system_users_granted)
        if system_user is None:
            self.client.send_unicode(_("No system user"))
            return
        forwarder = ProxyServer(self.client, asset, system_user)
        forwarder.proxy()

    #
    # Entrance
    #

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

    def close(self):
        logger.debug("Interactive server server close: {}".format(self))
        self.closed = True

    def interact_async(self):
        # 目前没用
        thread = threading.Thread(target=self.interact)
        thread.daemon = True
        thread.start()

    # def __del__(self):
    #     print("GC: Interactive class been gc")
