# coding: utf-8

import socket

import paramiko
import time

from .session import Session
from .models import Server
from .exception import PermissionFailed


class ProxyServer:
    def __init__(self, app, client, request):
        self.app = app
        self.request = request
        self.client = client
        self.server = None

    def proxy(self, asset, system_user):
        try:
            self.server = self.get_server_conn(asset, system_user)
        except PermissionFailed:
            self.client.send("No permission")
            return

        session = Session(self.client, self.server)
        self.app.sessions.append(session)
        session.bridge()
        self.app.sessions.remove(session)

    def validate_permission(self, asset, system_user):
        """
        Validate use is have the permission to connect this asset using that
        system user
        :return: True or False
        """
        return True

    def get_system_user_auth(self, system_user):
        """
        Get the system user auth ..., using this to connect asset
        :return: system user have full info
        """

    def get_server_conn(self, asset, system_user):
        if not self.validate_permission(asset, system_user):
            raise PermissionFailed

        self.get_system_user_auth(system_user)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(asset.ip, port=asset.port,
                        username=system_user.username,
                        password=system_user.password,
                        pkey=system_user.private_key)
        except paramiko.AuthenticationException as e:
            self.client.send("Authentication failed: %s" % e)
            return

        except socket.error as e:
            self.client.send("Connection server error: %s" % e)
            return

        term = self.request.meta.get('term', 'xterm')
        width = self.request.meta.get('width', 80)
        height = self.request.meta.get('height', 24)
        chan = ssh.invoke_shell(term, width=width, height=height)
        return Server(chan, asset, system_user)

