import os
import time
import threading

from .config import Config
from .sshd import SSHServer
from .logger import create_logger


__version__ = '0.4.0'

BASE_DIR = os.path.dirname(os.path.dirname(__file__))


class Coco:
    config_class = Config
    default_config = {
        'NAME': 'coco',
        'CORE_HOST': 'http://127.0.0.1:8080',
        'DEBUG': True,
        'BIND_HOST': '0.0.0.0',
        'SSHD_PORT': 2222,
        'WS_PORT': 5000,
        'ACCESS_KEY': '',
        'ACCESS_KEY_FILE': os.path.join(BASE_DIR, 'keys', '.access_key'),
        'SECRET_KEY': None,
        'LOG_LEVEL': 'INFO',
        'LOG_DIR': os.path.join(BASE_DIR, 'logs'),
        'ASSET_SORT_BY': 'hostname',  # hostname, ip
        'SSH_PASSWORD_AUTH': True,
        'SSH_PUBLIC_KEY_AUTH': True,
        'HEARTBEAT_INTERVAL': 5,
    }

    def __init__(self, name=None):
        self.config = self.config_class(BASE_DIR, defaults=self.default_config)
        self.sessions = []

        if name:
            self.name = name
        else:
            self.name = self.config['NAME']
        self.make_logger()

    def make_logger(self):
        create_logger(self)

    @staticmethod
    def bootstrap():
        pass

    def heartbeat(self):
        pass

    def run_forever(self):
        print(time.ctime())
        print('Coco version %s, more see https://www.jumpserver.org' % __version__)
        print('Starting ssh server at %(host)s:%(port)s' % {
            'host': self.config['BIND_HOST'], 'port': self.config['SSHD_PORT']})
        print('Starting websocket server at %(host)s:%(port)s' % {
            'host': self.config['BIND_HOST'], 'port': self.config['WS_PORT']})
        print('Quit the server with CONTROL-C.')

        try:
            self.run_sshd()
            self.run_ws()
        except KeyboardInterrupt:
            self.shutdown()

    def run_sshd(self):
        thread = threading.Thread(target=SSHServer.run, args=(self,))

    def run_ws(self):
        pass

    def shutdown(self):
        pass

    def monitor_session(self):
        pass

