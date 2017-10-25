#!coding: utf-8
import logging
import socket
import threading

from . import char
from .utils import TtyIOParser, wrap_with_line_feed as wr, \
    wrap_with_primary as primary, wrap_with_warning as warning
from .forward import ProxyServer
from .models import Asset, SystemUser
from .session import Session

logger = logging.getLogger(__file__)


class InteractiveServer:

    def __init__(self, app, client):
        self.app = app
        self.client = client
        self.request = client.do

    def display_banner(self):
        self.client.send(char.CLEAR_CHAR)

        banner = u"""\n\033[1;32m  %s, 欢迎使用Jumpserver开源跳板机系统  \033[0m\r\n\r
        1) 输入 \033[32mID\033[0m 直接登录 或 输入\033[32m部分 IP,主机名,备注\033[0m 进行搜索登录(如果唯一).\r
        2) 输入 \033[32m/\033[0m + \033[32mIP, 主机名 or 备注 \033[0m搜索. 如: /ip\r
        3) 输入 \033[32mP/p\033[0m 显示您有权限的主机.\r
        4) 输入 \033[32mG/g\033[0m 显示您有权限的主机组.\r
        5) 输入 \033[32mG/g\033[0m\033[0m + \033[32m组ID\033[0m 显示该组下主机. 如: g1\r
        6) 输入 \033[32mE/e\033[0m 批量执行命令.(未完成)\r
        7) 输入 \033[32mU/u\033[0m 批量上传文件.(未完成)\r
        8) 输入 \033[32mD/d\033[0m 批量下载文件.(未完成)\r
        9) 输入 \033[32mH/h\033[0m 帮助.\r
        0) 输入 \033[32mQ/q\033[0m 退出.\r\n""" % self.request.user
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

    def search_assets(self, opt, from_result=False):
        pass

    def display_assets(self):
        """
        Display user all assets
        :return:
        """
        pass

    def display_asset_groups(self):
        pass

    def display_group_assets(self):
        pass

    def display_search_result(self):
        pass

    def search_and_display(self, opt):
        self.search_assets(opt=opt)
        self.display_search_result()

    def get_user_asset_groups(self):
        pass

    def get_user_assets(self):
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
