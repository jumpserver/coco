#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import socket
import threading
import os
import math
import time
from treelib import Tree

from . import char
from .config import config
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

    def __init__(self, client):
        self.client = client
        self.closed = False
        self._search_result = None
        self.nodes = None
        self.offset = 0
        self.limit = 100
        self.assets_list = []
        self.finish = False
        self.page = 1
        self.total_assets = 0
        self.total_count = 0  # 分页展示中用来存放数目总条数
        self.nodes_tree = None  # 授权节点树
        self.get_user_assets_paging_async()
        self.get_user_nodes_async()

    @property
    def page_size(self):
        return self.client.request.meta['height'] - 8

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
            _("{T}5) Enter {green}g{end} + {green}NodeID{end} to display the host under the node, such as g1.{R}"),
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
            self.display_nodes_tree()
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
        if not self.finish:
            assets = app_service.get_search_user_granted_assets(self.client.user, q)
            return assets
        assets = self.assets_list
        result = []

        # 所有的
        if q in ('', None):
            result = assets

        # 全匹配到则直接返回全匹配的
        if len(result) == 0:
            _result = [asset for asset in assets
                       if is_obj_attr_eq(asset, q)]
            if len(_result) == 1:
                result = _result

        # 最后模糊匹配
        if len(result) == 0:
            result = [asset for asset in assets
                      if is_obj_attr_has(asset, q)]

        return result

    def display_assets(self):
        """
        Display user all assets
        :return:
        """
        self.display_result_paging(self.assets_list)

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

    def display_nodes_tree(self):
        if self.nodes is None:
            self.get_user_nodes()

        if not self.nodes:
            self.client.send(wr(_('No Nodes'), before=1))
            return

        self.nodes_tree.show(key=lambda node: node.identifier)
        self.client.send(wr(title(_("Node: [ ID.Name(Asset amount) ]")), before=1))
        self.client.send(wr(self.nodes_tree._reader.replace('\n', '\r\n'), before=1))
        prompt = _("Tips: Enter g+NodeID to display the host under the node, such as g1")
        self.client.send(wr(title(prompt), before=1))

    def display_node_assets(self, _id):
        if self.nodes is None:
            self.get_user_nodes()
        if _id > len(self.nodes) or _id <= 0:
            msg = wr(warning(_("There is no matched node, please re-enter")))
            self.client.send(msg)
            self.display_nodes_tree()
            return

        assets = self.nodes[_id - 1].assets_granted
        self.display_result_paging(assets)

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

        total_page = math.ceil(self.total_count/self.page_size)
        self.client.send(wr(title(_("Page: {}, Count: {}, Total Page: {}, Total Count: {}").format(
            self.page, len(self.search_result), total_page, self.total_count)), before=1)
        )

    def search_and_display(self, q):
        assets = self.search_assets(q)
        self.display_result_paging(assets)

    def get_user_nodes(self):
        self.nodes = app_service.get_user_asset_groups(self.client.user)
        self.sort_nodes()
        self.construct_nodes_tree()

    def sort_nodes(self):
        self.nodes = sorted(self.nodes, key=lambda node: node.key)

    def construct_nodes_tree(self):
        self.nodes_tree = Tree()
        for index, node in enumerate(self.nodes):
            tag = "{}.{}({})".format(index+1, node.name, node.assets_amount)
            key = node.key
            parent_key = key[:node.key.rfind(':')] or None
            self.nodes_tree.create_node(tag=tag, identifier=key, data=node, parent=parent_key)

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

    def get_user_assets_paging(self):
        while not self.closed:
            assets, total = app_service.get_user_assets_paging(
                self.client.user, offset=self.offset, limit=self.limit
            )
            logger.info('Get user assets paging async: {}'.format(len(assets)))
            if not assets:
                logger.info('Get user assets paging async finished.')
                self.finish = True
                return
            if not self.total_assets:
                self.total_assets = total
                self.total_count = total
            self.assets_list.extend(assets)
            self.offset += self.limit

    def get_user_assets_paging_async(self):
        thread = threading.Thread(target=self.get_user_assets_paging)
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
        assets = self.search_assets(opt)
        if assets and len(assets) == 1:
            asset = assets[0]
            self.search_result = None
            if asset.platform == "Windows":
                self.client.send(warning(
                    _("Terminal does not support login Windows, "
                      "please use web terminal to access"))
                )
                return
            self.proxy(asset)
        else:
            self.display_result_paging(assets)

    def display_result_paging(self, result_list):

        if result_list is self.assets_list:
            self.total_count = self.total_assets
        else:
            if len(result_list) == 0:
                return
            self.total_count = len(result_list)

        action = PAGE_DOWN
        gen_result = self.get_result_page_down_or_up(result_list)
        while True:
            try:
                page, result = gen_result.send(action)
            except TypeError:
                try:
                    page, result = next(gen_result)
                except StopIteration:
                    logger.info('No Assets')
                    self.display_banner()
                    self.client.send(wr(_("No Assets"), before=1))
                    return None
            except StopIteration:
                logger.info('Back display result paging.')
                self.display_banner()
                return None
            self.display_result_of_page(page, result)
            action = self.get_user_action()

    def get_result_page_down_or_up(self, result_list):
        left = 0
        page = 1
        page_up_size = 0  # 记录上一页大小
        while True:
            right = left + self.page_size
            result = result_list[left:right]

            if not result and (result_list is self.assets_list) and self.finish and self.total_assets == 0:
                # 无授权资产
                return None, None

            elif not result and (result_list is self.assets_list) and self.finish:
                # 上一页是最后一页
                left -= page_up_size
                page -= 1
                continue
            elif not result and (result_list is self.assets_list) and not self.finish:
                # 还有下一页(暂时没有加载完)，需要等待
                time.sleep(1)
                continue
            elif not result and (result_list is not self.assets_list):
                # 上一页是最后一页
                left -= page_up_size
                page -= 1
                continue
            else:
                # 其他4中情况，返回assets
                action = yield (page, result)

                if action == BACK:
                    return None, None
                elif action == PAGE_UP:
                    if page <= 1:
                        # 已经是第一页了
                        page = 1
                        left = 0
                    else:
                        page -= 1
                        left -= self.page_size
                else:
                    # PAGE_DOWN
                    page += 1
                    left += len(result)
                    page_up_size = len(result)

    def display_result_of_page(self, page, result):
        self.client.send(char.CLEAR_CHAR)
        self.page = page
        self.search_result = result
        self.display_search_result()
        self.display_prompt_of_page()

    def display_prompt_of_page(self):
        self.client.send(wr(_('Tips: Enter the asset ID and log directly into the asset.'), before=1))
        prompt_page_up = _("Page up: P/p")
        prompt_page_down = _("Page down: Enter|N/n")
        prompt_back = _("BACK: b/q")
        prompts = [prompt_page_up, prompt_page_down, prompt_back]
        prompt = '\t'.join(prompts)
        self.client.send(wr(prompt, before=1))

    def get_user_action(self):
        opt = net_input(self.client, prompt=':')
        if opt in ('p', 'P'):
            return PAGE_UP
        elif opt in ('b', 'q'):
            return BACK
        elif opt.isdigit() and self.search_result and 0 < int(opt) <= len(self.search_result):
            self.proxy(self.search_result[int(opt)-1])
            return BACK
        else:
            # PAGE_DOWN
            return PAGE_DOWN

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
