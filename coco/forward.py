# coding: utf-8

import socket
import threading
import logging

import paramiko
import time

from .session import Session
from .models import Server


logger = logging.getLogger(__file__)
TIMEOUT = 8


class ProxyServer:
    def __init__(self, app, client):
        self.app = app
        self.client = client
        self.request = client.do
        self.server = None
        self.connecting = True

    def proxy(self, asset, system_user):
        self.send_connecting_message()
        self.server = self.get_server_conn(asset, system_user)
        if self.server is None:
            return
        session = Session(self.client, self.server)
        self.app.sessions.append(session)
        self.watch_win_size_change_async()
        session.record_async()
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
        logger.info("Connect to %s" % asset.hostname)
        if not self.validate_permission(asset, system_user):
            self.client.send(b'No permission')
            return None

        self.get_system_user_auth(system_user)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(asset.ip, port=asset.port,
                        username=system_user.username,
                        password=system_user.password,
                        pkey=system_user.private_key,
                        timeout=TIMEOUT)
        except paramiko.AuthenticationException as e:
            self.client.send("[Errno 66] Authentication failed: {}".format(e).encode("utf-8"))
            return None

        except socket.error as e:
            self.client.send(" {}".format(e).encode("utf-8"))
            return None
        finally:
            self.connecting = False
            self.client.send(b'\r\n')

        term = self.request.meta.get('term', 'xterm')
        width = self.request.meta.get('width', 80)
        height = self.request.meta.get('height', 24)
        chan = ssh.invoke_shell(term, width=width, height=height)
        return Server(chan, asset, system_user)

    def watch_win_size_change(self):
        while self.request.change_size_event.wait():
            self.request.change_size_event.clear()
            width = self.request.meta.get('width', 80)
            height = self.request.meta.get('height', 24)
            logger.debug("Change win size: %s - %s" % (width, height))
            self.server.chan.resize_pty(width=width, height=height)

    def watch_win_size_change_async(self):
        thread = threading.Thread(target=self.watch_win_size_change)
        thread.daemon = True
        thread.start()

    def send_connecting_message(self):
        def func():
            delay = 0.0
            self.client.send('Connecting to {} {:.1f}'.format('abc.com', delay).encode('utf-8'))
            while self.connecting and delay < TIMEOUT:
                self.client.send('\x08\x08\x08{:.1f}'.format(delay).encode('utf-8'))
                time.sleep(0.1)
                delay += 0.1
        thread = threading.Thread(target=func)
        thread.daemon = True
        thread.start()

