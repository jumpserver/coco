# -*- coding: utf-8 -*-
#

import os
import socket

import paramiko
from paramiko.ssh_exception import SSHException

from .ctx import app_service
from .utils import get_logger, get_private_key_fingerprint

logger = get_logger(__file__)
TIMEOUT = 10


class SSHConnection:
    def get_system_user_auth(self, system_user):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        password, private_key = \
            app_service.get_system_user_auth_info(system_user)
        system_user.password = password
        system_user.private_key = private_key

    def get_ssh_client(self, asset, system_user):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sock = None

        if not system_user.password and not system_user.private_key:
            self.get_system_user_auth(system_user)

        if asset.domain:
            sock = self.get_proxy_sock_v2(asset)

        try:
            ssh.connect(
                asset.ip, port=asset.port, username=system_user.username,
                password=system_user.password, pkey=system_user.private_key,
                timeout=TIMEOUT, compress=True, auth_timeout=TIMEOUT,
                look_for_keys=False, sock=sock
            )
        except (paramiko.AuthenticationException,
                paramiko.BadAuthenticationType,
                SSHException) as e:
            password_short = "None"
            key_fingerprint = "None"
            if system_user.password:
                password_short = system_user.password[:5] + \
                                 (len(system_user.password) - 5) * '*'
            if system_user.private_key:
                key_fingerprint = get_private_key_fingerprint(
                    system_user.private_key
                )

            logger.error("Connect {}@{}:{} auth failed, password: \
                                 {}, key: {}".format(
                system_user.username, asset.ip, asset.port,
                password_short, key_fingerprint,
            ))
            return None, None, str(e)
        except (socket.error, TimeoutError) as e:
            return None, None, str(e)
        return ssh, sock, None

    def get_transport(self, asset, system_user):
        ssh, sock, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            return ssh.get_transport(), sock, None
        else:
            return None, None, msg

    def get_channel(self, asset, system_user, term="xterm", width=80, height=24):
        ssh, sock, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            chan = ssh.invoke_shell(term, width=width, height=height)
            return chan, sock, None
        else:
            return None, sock, msg

    def get_sftp(self, asset, system_user):
        ssh, sock, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            return ssh.open_sftp(), sock, None
        else:
            return None, sock, msg

    @staticmethod
    def get_proxy_sock_v2(asset):
        sock = None
        domain = app_service.get_domain_detail_with_gateway(
            asset.domain
        )
        if not domain.has_ssh_gateway():
            return None
        for i in domain.gateways:
            gateway = domain.random_ssh_gateway()
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                ssh.connect(gateway.ip, username=gateway.username,
                            password=gateway.password,
                            port=gateway.port,
                            pkey=gateway.private_key_obj)
            except(paramiko.AuthenticationException,
                   paramiko.BadAuthenticationType,
                   SSHException):
                continue
            sock = ssh.get_transport().open_channel(
                'direct-tcpip', (asset.ip, asset.port), ('127.0.0.1', 0)
            )
            break
        return sock

    def get_proxy_sock(self, asset):
        sock = None
        domain = app_service.get_domain_detail_with_gateway(
            asset.domain
        )
        if not domain.has_ssh_gateway():
            return None
        for i in domain.gateways:
            gateway = domain.random_ssh_gateway()
            proxy_command = [
                "ssh", "-o", "StrictHostKeyChecking=no",
                "-p", str(gateway.port),
                "{}@{}".format(gateway.username, gateway.ip),
                "-W", "{}:{}".format(asset.ip, asset.port), "-q",
            ]

            if gateway.password:
                proxy_command.insert(0, "sshpass -p {}".format(gateway.password))

            if gateway.private_key:
                gateway.set_key_dir(os.path.join(self.app.root_path, 'keys'))
                proxy_command.append("-i {}".format(gateway.private_key_file))
            proxy_command = ' '.join(proxy_command)

            try:
                sock = paramiko.ProxyCommand(proxy_command)
                break
            except (paramiko.AuthenticationException,
                    paramiko.BadAuthenticationType, SSHException,
                    TimeoutError) as e:
                logger.error(e)
                continue
        return sock
