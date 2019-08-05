# -*- coding: utf-8 -*-
#

import re
import socket
import telnetlib
from .const import MANUAL_LOGIN


try:
    import selectors
except ImportError:
    import selectors2 as selectors

import paramiko

from .service import app_service
from .conf import config
from .utils import get_logger, get_private_key_fingerprint

logger = get_logger(__file__)

BUF_SIZE = 1024
MANUAL_LOGIN = 'manual'
AUTO_LOGIN = 'auto'


class SSHConnection:
    connections = {}

    @staticmethod
    def make_key(user, asset, system_user):
        key = "{}_{}_{}".format(user.id, asset.id, system_user.id)
        return key

    @classmethod
    def new_connection_from_cache(cls, user, asset, system_user):
        if not config.REUSE_CONNECTION:
            return None
        key = cls.make_key(user, asset, system_user)
        connection = cls.connections.get(key)
        if not connection:
            return None
        if not connection.is_active:
            cls.connections.pop(key, None)
            return None
        connection.ref += 1
        return connection

    @classmethod
    def set_connection_to_cache(cls, conn):
        if not config.REUSE_CONNECTION:
            return None
        key = cls.make_key(conn.user, conn.asset, conn.system_user)
        cls.connections[key] = conn

    @classmethod
    def new_connection(cls, user, asset, system_user):
        connection = cls.new_connection_from_cache(user, asset, system_user)

        if connection:
            logger.debug("Reuse connection: {}->{}@{}".format(
                user.username, asset.ip, system_user.username)
            )
            return connection
        connection = cls(user, asset, system_user)
        connection.connect()
        if connection.is_active:
            cls.set_connection_to_cache(connection)
        return connection

    @classmethod
    def remove_ssh_connection(cls, conn):
        key = "{}_{}_{}".format(conn.user.id, conn.asset.id, conn.system_user.id)
        cls.connections.pop(key, None)

    def __init__(self, user, asset, system_user):
        self.user = user
        self.asset = asset
        self.system_user = system_user
        self.client = None
        self.transport = None
        self.sock = None
        self.error = ""
        self.ref = 1

    def get_system_user_auth(self):
        """
        获取系统用户的认证信息，密码或秘钥
        :return: system user have full info
        """
        if self.system_user.login_mode == MANUAL_LOGIN:
            return
        password, private_key = \
            app_service.get_system_user_auth_info(self.system_user, self.asset)
        self.system_user.password = password
        self.system_user.private_key = private_key

    def connect(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        sock = None
        error = ''

        if not self.system_user.password and not self.system_user.private_key:
            self.get_system_user_auth()

        if self.asset.domain:
            sock = self.get_proxy_sock_v2(self.asset)
            if not sock:
                error = 'Connect gateway failed.'
                logger.error(error)

        asset = self.asset
        system_user = self.system_user
        try:
            try:
                ssh.connect(
                    asset.ip, port=asset.ssh_port, username=system_user.username,
                    password=system_user.password, pkey=system_user.private_key,
                    timeout=config['SSH_TIMEOUT'],
                    compress=False, auth_timeout=config['SSH_TIMEOUT'],
                    look_for_keys=False, sock=sock
                )
            except paramiko.AuthenticationException:
                # 思科设备不支持秘钥登陆，提供秘钥，必然失败
                ssh.connect(
                    asset.ip, port=asset.ssh_port, username=system_user.username,
                    password=system_user.password, timeout=config['SSH_TIMEOUT'],
                    compress=False, auth_timeout=config['SSH_TIMEOUT'],
                    look_for_keys=False, sock=sock, allow_agent=False,
                )
            transport = ssh.get_transport()
            transport.set_keepalive(60)
            self.transport = transport
        except Exception as e:
            password_short = "None"
            key_fingerprint = "None"
            if system_user.password:
                password_short = system_user.password[:5] + \
                                 (len(system_user.password) - 5) * '*'
            if system_user.private_key:
                key_fingerprint = get_private_key_fingerprint(
                    system_user.private_key
                )
            msg = "Connect {}@{}:{} auth failed, password: {}, key: {}".format(
                system_user.username, asset.ip, asset.ssh_port,
                password_short, key_fingerprint,
            )
            logger.error(msg)
            error += '\r\n' + str(e) if error else str(e)
            ssh, sock, error = None, None, error
        self.client = ssh
        self.sock = ssh
        self.error = error

    def reconnect_if_need(self):
        if not self.is_active:
            self.connect()

        if self.is_active:
            return True
        return False

    def get_transport(self):
        if self.reconnect_if_need():
            return self.transport
        return None

    def get_channel(self, term="xterm", width=80, height=24):
        if self.reconnect_if_need():
            chan = self.client.invoke_shell(term, width=width, height=height)
            return chan
        else:
            return None

    def get_sftp(self):
        if self.reconnect_if_need():
            return self.client.open_sftp()
        else:
            return None

    @property
    def is_active(self):
        return self.transport and self.transport.is_active()

    def close(self):
        if self.ref > 1:
            self.ref -= 1
            msg = "Connection ref -1: {}->{}@{}. {}".format(
                self.user.username, self.asset.hostname,
                self.system_user.username, self.ref
            )
            logger.debug(msg)
            return
        self.__class__.remove_ssh_connection(self)
        try:
            self.client.close()
            if self.sock:
                self.sock.close()
        except Exception as e:
            logger.error("Close connection error: ", e)

        msg = "Close connection: {}->{}@{}. Total connections live: {}".format(
            self.user.username, self.asset.ip,
            self.system_user.username, len(self.connections)
        )
        logger.debug(msg)

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
                ssh.connect(gateway.ip, port=gateway.port,
                            username=gateway.username,
                            password=gateway.password,
                            pkey=gateway.private_key_obj,
                            timeout=config['SSH_TIMEOUT'])
            except Exception as e:
                logger.error("Connect gateway error")
                logger.error(e, exc_info=True)
                continue
            try:
                transport = ssh.get_transport()
                transport.set_keepalive(60)
                sock = transport.open_channel(
                    'direct-tcpip', (asset.ip, asset.ssh_port), ('127.0.0.1', 0)
                )
                break
            except Exception as e:
                logger.error("Open gateway channel error")
                logger.error(e, exc_info=True)
                continue
        return sock


class TelnetConnection:
    incorrect_pattern = re.compile(
        r'incorrect|failed|失败|错误', re.I
    )
    username_pattern = re.compile(
        r'login:?\s*$|username:?\s*$|用户名:?\s*$|账\s*号:?\s*$', re.I
    )
    password_pattern = re.compile(
        r'Password:?\s*$|passwd:?\s*$|密\s*码:?\s*$', re.I
    )
    success_pattern = re.compile(r'Last\s*login|success|成功|#|>|\$', re.I)
    custom_success_pattern = None

    def __init__(self, asset, system_user, client):
        self.client = client
        self.asset = asset
        self.system_user = system_user
        self.sock = None
        self.sel = selectors.DefaultSelector()
        if config.TELNET_REGEX:
            try:
                self.custom_success_pattern = re.compile(
                    r'{}'.format(config.TELNET_REGEX), re.I
                )
            except (TypeError, ValueError):
                pass

    def get_socket(self):
        logger.debug('Get telnet server socket. {}'.format(self.client.user))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        try:
            self.sock.connect((self.asset.ip, self.asset.telnet_port))
        except Exception as e:
            msg = 'Connect telnet server failed. \r\n{}'.format(e)
            logger.error(msg)
            return None, msg
        # Send SGA and ECHO options to Telnet Server
        self.sock.send(telnetlib.IAC + telnetlib.DO + telnetlib.SGA)
        self.sock.send(telnetlib.IAC + telnetlib.DO + telnetlib.ECHO)
        self.sel.register(self.sock, selectors.EVENT_READ)

        while True:
            events = self.sel.select()
            for sock in [key.fileobj for key, _ in events]:
                data = sock.recv(BUF_SIZE)
                if sock == self.sock:
                    logger.debug(b'[Telnet server send]: ' + data)

                    if not data:
                        self.sock.close()
                        msg = 'The server <{}> closes the connection.'.format(
                            self.asset.hostname
                        )
                        logger.info(msg)
                        return None, msg

                    # 将数据以 \r\n 进行分割
                    _data_list = data.split(b'\r\n')
                    for _data in _data_list:
                        if not _data:
                            continue

                        if _data.startswith(telnetlib.IAC):
                            self.option_negotiate(_data)
                        else:
                            result = self.login_auth(_data)
                            if result:
                                msg = 'Successful asset connection.<{}>/<{}>/<{}>.'.format(
                                    self.client.user, self.system_user.username,
                                    self.asset.hostname
                                )
                                logger.info(msg)
                                return self.sock, None
                            elif result is False:
                                self.sock.close()
                                msg = 'Authentication failed.\r\n'
                                logger.info(msg)
                                return None, msg
                            elif result is None:
                                continue

    def option_negotiate(self, data):
        """
        Telnet server option negotiate before connection
        :param data: option negotiate data
        :return:
        """
        logger.debug(b'[Server options negotiate]: ' + data)
        data_list = data.split(telnetlib.IAC)
        new_data_list = []
        for x in data_list:
            if x == telnetlib.DO + telnetlib.ECHO:
                new_data_list.append(telnetlib.WONT + telnetlib.ECHO)
            elif x == telnetlib.WILL + telnetlib.ECHO:
                new_data_list.append(telnetlib.DO + telnetlib.ECHO)
            elif x == telnetlib.WILL + telnetlib.SGA:
                new_data_list.append(telnetlib.DO + telnetlib.SGA)
            elif x == telnetlib.DO + telnetlib.TTYPE:
                new_data_list.append(telnetlib.WILL + telnetlib.TTYPE)
            elif x == telnetlib.SB + telnetlib.TTYPE + b'\x01':
                new_data_list.append(telnetlib.SB + telnetlib.TTYPE + b'\x00' + b'XTERM-256COLOR')
            elif telnetlib.DO in x:
                new_data_list.append(x.replace(telnetlib.DO, telnetlib.WONT))
            elif telnetlib.WILL in x:
                new_data_list.append(x.replace(telnetlib.WILL, telnetlib.DONT))
            elif telnetlib.WONT in x:
                new_data_list.append(x.replace(telnetlib.WONT, telnetlib.DONT))
            elif telnetlib.DONT in x:
                new_data_list.append(x.replace(telnetlib.DONT, telnetlib.WONT))
            else:
                new_data_list.append(x)
        new_data = telnetlib.IAC.join(new_data_list)
        logger.debug(b'[Client options negotiate]: ' + new_data)
        self.sock.send(new_data)

    def login_auth(self, raw_data):
        logger.debug('[Telnet login auth]: ({})'.format(self.client.user))

        try:
            data = raw_data.decode('utf-8')
        except UnicodeDecodeError:
            try:
                data = raw_data.decode('gbk')
            except UnicodeDecodeError:
                logger.debug(b'[Decode error]: ' + b'>>' + raw_data + b'<<')
                return None

        if self.incorrect_pattern.search(data):
            logger.debug(b'[Login incorrect prompt]: ' + b'>>' + raw_data + b'<<')
            return False
        elif self.username_pattern.search(data):
            logger.debug(b'[Username prompt]: ' + b'>>' + raw_data + b'<<')
            self.sock.send(self.system_user.username.encode('utf-8') + b'\r\n')
            return None
        elif self.password_pattern.search(data):
            logger.debug(b'[Password prompt]: ' + b'>>' + raw_data + b'<<')
            self.sock.send(self.system_user.password.encode('utf-8') + b'\r\n')
            return None
        elif self.success_pattern.search(data) or \
                (self.custom_success_pattern and
                 self.custom_success_pattern.search(data)):
            self.client.send(raw_data)
            logger.debug(b'[Login Success prompt]: ' + b'>>' + raw_data + b'<<')
            return True
        else:
            logger.debug(b'[No match]: ' + b'>>' + raw_data + b'<<')
            return None
