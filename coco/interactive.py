#!coding: utf-8
import socket

from . import char


class InteractiveServer:

    def __init__(self, app, request, chan):
        self.app = app
        self.request = request
        self.client = chan

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
        self.client.send(banner)

    def get_input(self, prompt='Opt> '):
        pass

    def dispatch(self):
        pass

    def run(self):
        self.display_banner()
        while True:
            try:
                self.dispatch()
            except socket.error:
                break
        self.close()

    def close(self):
        pass
