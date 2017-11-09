#!coding: utf-8
import logging
import socket
import threading

# Todo remove
from jms.models import Asset, SystemUser

from . import char
from .utils import wrap_with_line_feed as wr, wrap_with_title as title, \
    wrap_with_primary as primary, wrap_with_warning as warning, \
    is_obj_attr_has, is_obj_attr_eq, sort_assets, TtyIOParser
from .forward import ProxyServer
from .session import Session

logger = logging.getLogger(__file__)


class InteractiveServer:

    def __init__(self, app, client):
        self.app = app
        self.client = client
        self.request = client.request
        self.assets = None
        self.search_result = None
        self.asset_groups = None
        self.get_user_assets_async()

    def display_banner(self):
        self.client.send(char.CLEAR_CHAR)

        banner = u"""\n {title} {user}, 欢迎使用Jumpserver开源跳板机系统  {end}\r\n\r
        1) 输入 {green}ID{end} 直接登录 或 输入{green}部分 IP,主机名,备注{end} 进行搜索登录(如果唯一).\r
        2) 输入 {green}/{end} + {green}IP, 主机名 or 备注 {end}搜索. 如: /ip\r
        3) 输入 {green}P/p{end} 显示您有权限的主机.\r
        4) 输入 {green}G/g{end} 显示您有权限的主机组.\r
        5) 输入 {green}G/g{end}{end} + {green}组ID{end} 显示该组下主机. 如: g1\r
        6) 输入 {green}E/e{end} 批量执行命令.(未完成)\r
        7) 输入 {green}U/u{end} 批量上传文件.(未完成)\r
        8) 输入 {green}D/d{end} 批量下载文件.(未完成)\r
        9) 输入 {green}H/h{end} 帮助.\r
        0) 输入 {green}Q/q{end} 退出.\r\n""".format(
            title="\033[1;32m", green="\033[32m", end="\033[0m", user=self.client.user)
        self.client.send(banner.encode('utf-8'))

    def get_choice(self, prompt=b'Opt> '):
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

            # Todo: Move x1b to char
            if data.startswith(b'\x1b') or data in char.UNSUPPORTED_CHAR:
                self.client.send(b'')
                continue

            # handle shell expect
            multi_char_with_enter = False
            if len(data) > 1 and data[-1] in char.ENTER_CHAR:
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
        if opt in ['q', 'Q', '0']:
            self.app.remove_client(self.client)
        elif opt in ['h', 'H', '9']:
            self.display_banner()
        elif opt in ['p', 'P', '3']:
            self.display_assets()
        elif opt in ['g', 'G', '5']:
            self.display_asset_groups()
        else:
            self.search_and_proxy(opt)

    def search_assets(self, q, from_result=False):
        if self.assets is None:
            self.get_user_assets()
        if from_result:
            source = self.search_result
        else:
            source = self.assets

        result = []
        # 用户输入的是数字，可能想使用id唯一键搜索
        if q.isdigit():
            if len(source) > int(q):
                result = [source[q-1]]

        # 全匹配则直接返回
        if len(result) == 0:
            _result = [asset for asset in source if is_obj_attr_eq(asset, q)]
            if len(_result) == 1:
                result = _result

        # 最后模糊匹配
        if len(result) == 0:
            result = [asset for asset in source if is_obj_attr_has(asset, q)]

        self.search_result = sort_assets(result, self.app.config["ASSET_LIST_SORT_BY"])

    def display_assets(self):
        """
        Display user all assets
        :return:
        """
        self.search_and_display('')

    def display_group_assets(self):
        pass

    def display_search_result(self):
        if len(self.search_result) == 0:
            self.client.send(warning("Nothing match"))
            return

        fake_asset = Asset(hostname="Hostname", ip="IP", system_users_join="LoginAs", comment="Comment")
        id_max_length = max(len(str(len(self.search_result))), 3)
        hostname_max_length = max(max([len(asset.hostname) for asset in self.search_result + [fake_asset]]), 15)
        sysuser_max_length = max([len(asset.system_users_join) for asset in self.search_result + [fake_asset]])
        header = '{1:%d} {0.hostname:%d} {0.ip:15} {0.system_users_join:%d} ' % \
                 (id_max_length, hostname_max_length, sysuser_max_length)
        comment_length = self.request.meta["width"] - len(header.format(fake_asset, id_max_length))
        line = header + '{0.comment:.%d}' % (comment_length / 2)  # comment中可能有中文
        header += '{0.comment:%s}' % comment_length
        self.client.send(wr(title(header.format(fake_asset, "ID").encode("utf-8"))))
        self.client.send(b'\r\n')
        for index, asset in enumerate(self.search_result, 1):
            self.client.send(line.format(asset, index).encode('utf-8'))
            self.client.send(b'\r\n')

    def search_and_display(self, q):
        self.search_assets(q)
        self.display_search_result()

    def get_user_asset_groups(self):
        pass

    def get_user_asset_groups_async(self):
        thread = threading.Thread(target=self.get_user_asset_groups)
        thread.start()

    def get_user_assets(self):
        self.assets = self.app.service.get_user_assets(self.client.user)

    def get_user_assets_async(self):
        thread = threading.Thread(target=self.get_user_assets)
        thread.start()

    def display_asset_groups(self):
        pass

    def choose_system_user(self, system_users):
        pass

    def search_and_proxy(self, opt, from_result=False):
        asset = Asset(id=1, hostname="testserver", ip="123.57.183.135", port=8022)
        system_user = SystemUser(id=2, username="web", password="redhat123", name="web")
        self.proxy(asset, system_user)

    def proxy(self, asset, system_user):
        forwarder = ProxyServer(self.app, self.client)
        forwarder.proxy(asset, system_user)

    def replay_session(self, session_id):
        session = Session(self.client, None)
        session.id = "5a5dbfbe-093f-4bc1-810f-e8401b9e6045"
        session.replay()

    def activate(self):
        self.display_banner()
        while True:
            try:
                opt = self.get_choice()
                self.dispatch(opt)
            except socket.error as e:
                logger.error("Socket error %s" % e)
                break
        self.close()

    def activate_async(self):
        thread = threading.Thread(target=self.activate)
        thread.daemon = True
        thread.start()

    def close(self):
        pass
