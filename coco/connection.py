# -*- coding: utf-8 -*-
#

import weakref
import os
import socket

import paramiko
from paramiko.ssh_exception import SSHException

from .utils import get_logger, get_private_key_fingerprint

logger = get_logger(__file__)
TIMEOUT = 10


class SSHConnection:
    def __init__(self, app):
        self._app = weakref.ref(app)

    @property
    def app(self):
        return self._app()

    def get_ssh_client(self, asset, system_user):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sock = None
        self.get_system_user_auth(system_user)

        if asset.domain:
            sock = self.get_proxy_sock(asset)

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
            return None, str(e)
        except (socket.error, TimeoutError) as e:
            return None, str(e)
        return ssh, None

    def get_transport(self, asset, system_user):
        ssh, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            return ssh.get_transport(), None
        else:
            return None, msg

    def get_channel(self, asset, system_user, term="xterm", width=80, height=24):
        ssh, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            chan = ssh.invoke_shell(term, width=width, height=height)
            return chan, None
        else:
            return None, msg

    def get_sftp(self, asset, system_user):
        ssh, msg = self.get_ssh_client(asset, system_user)
        if ssh:
            return ssh.open_sftp(), None
        else:
            return None, msg

    def get_system_user_auth(self, system_user):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        system_user.password, system_user.private_key = \
            self.app.service.get_system_user_auth_info(system_user)

    def get_proxy_sock(self, asset):
        sock = None
        domain = self.app.service.get_domain_detail_with_gateway(
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
