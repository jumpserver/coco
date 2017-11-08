import os
import time
import threading
import logging
from jms.service import AppService

from .config import Config
from .sshd import SSHServer
from .httpd import HttpServer
from .logging import create_logger


__version__ = '0.4.0'

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = logging.getLogger(__file__)


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
        'ACCESS_KEY_ENV': 'COCO_ACCESS_KEY',
        'ACCESS_KEY_FILE': os.path.join(BASE_DIR, 'keys', '.access_key'),
        'SECRET_KEY': None,
        'LOG_LEVEL': 'INFO',
        'LOG_DIR': os.path.join(BASE_DIR, 'logs'),
        'SESSION_DIR': os.path.join(BASE_DIR, 'sessions'),
        'ASSET_LIST_SORT_BY': 'hostname',  # hostname, ip
        'SSH_PASSWORD_AUTH': True,
        'SSH_PUBLIC_KEY_AUTH': True,
        'HEARTBEAT_INTERVAL': 5,
        'MAX_CONNECTIONS': 500,
    }

    def __init__(self, name=None, root_path=None):
        self.config = self.config_class(BASE_DIR, defaults=self.default_config)
        self.sessions = []
        self.clients = []
        self.root_path = root_path
        self.name = name
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.service = None

        if name is None:
            self.name = self.config['NAME']
        if root_path is None:
            self.root_path = BASE_DIR

        self.httpd = None
        self.sshd = None
        self.running = True

    def make_logger(self):
        create_logger(self)

    def prepare(self):
        self.make_logger()
        self.sshd = SSHServer(self)
        self.httpd = HttpServer(self)
        self.initial_service()

    def heartbeat(self):
        pass

    def run_forever(self):
        self.prepare()
        print(time.ctime())
        print('Coco version %s, more see https://www.jumpserver.org' % __version__)
        print('Quit the server with CONTROL-C.')

        try:
            if self.config["SSHD_PORT"] != 0:
                self.run_sshd()

            if self.config['WS_PORT'] != 0:
                self.run_ws()

            self.stop_evt.wait()
        except KeyboardInterrupt:
            self.stop_evt.set()
            self.shutdown()

    def run_sshd(self):
        thread = threading.Thread(target=self.sshd.run, args=())
        thread.daemon = True
        thread.start()

    def run_ws(self):
        thread = threading.Thread(target=self.httpd.run, args=())
        thread.daemon = True
        thread.start()

    def shutdown(self):
        for client in self.clients:
            self.remove_client(client)
        time.sleep(1)
        self.sshd.shutdown()
        logger.info("Grace shutdown the server")

    def add_client(self, client):
        with self.lock:
            self.clients.append(client)
            logger.info("New client %s join, total %d now" % (client, len(self.clients)))

    def remove_client(self, client):
        with self.lock:
            try:
                self.clients.remove(client)
                logger.info("Client %s leave, total %d now" % (client, len(self.clients)))

                client.send("Closed by server")
                client.close()
            except:
                pass

    def initial_service(self):
        self.service = AppService(self)
        self.service.initial()

    def monitor_session(self):
        pass

