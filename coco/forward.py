#coding: utf-8
import socket

import paramiko

from .session import Session


class ProxyServer:
    def __init__(self, app, request, client):
        self.app = app
        self.request = request
        self.client = client
        self.server = None

    def proxy(self, asset, system_user):
        self.server = self.get_server_conn(asset, system_user)
        session = Session(self.client, self.server)
        session.bridge()

    def validate_permission(self, asset, system_user):
        """
        Validate use is have the permission to connect this asset using that
        system user
        :return: True or False
        """
        pass

    def get_system_user_info(self, system_user):
        """
        Get the system user auth ..., using this to connect asset
        :return: system user have full info
        """
        pass

    def get_server_conn(self, asset, system_user):

        self.ssh = ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(asset.ip, port=asset.port, username=system_user.username,
                    password=system_user.password, pkey=system_user.private_key)
        except (paramiko.AuthenticationException,) as e:
            pass

        except socket.error:
            pass

        return

