import datetime
import os
import time
import threading
import logging
import multiprocessing

from jms.service import AppService

from .config import Config
from .sshd import SSHServer
from .httpd import HttpServer
from .logging import create_logger
from .queue import MemoryQueue
from .record import ServerCommandRecorder, ServerReplayRecorder, \
    START_SENTINEL, DONE_SENTINEL


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
        'HTTPD_PORT': 5000,
        'ACCESS_KEY': '',
        'ACCESS_KEY_ENV': 'COCO_ACCESS_KEY',
        'ACCESS_KEY_FILE': os.path.join(BASE_DIR, 'keys', '.access_key'),
        'SECRET_KEY': None,
        'LOG_LEVEL': 'INFO',
        'LOG_DIR': os.path.join(BASE_DIR, 'logs'),
        'SESSION_DIR': os.path.join(BASE_DIR, 'sessions'),
        'REPLAY_STORE_ENGINE': 'server',   # local, server
        'COMMAND_STORE_ENGINE': 'server',  # local, server, elasticsearch(not yet)
        'ASSET_LIST_SORT_BY': 'hostname',  # hostname, ip
        'SSH_PASSWORD_AUTH': True,
        'SSH_PUBLIC_KEY_AUTH': True,
        'HEARTBEAT_INTERVAL': 5,
        'MAX_CONNECTIONS': 500,
        'ADMINS': '',
        'QUEUE_ENGINE': 'memory',
        'QUEUE_MAX_SIZE': 0,
        'MAX_PUSH_THREADS': 5,
        # 'MAX_RECORD_OUTPUT_LENGTH': 4096,
    }

    def __init__(self, name=None, root_path=None):
        self.root_path = root_path if root_path else BASE_DIR
        self.config = self.config_class(self.root_path, defaults=self.default_config)
        self.name = name if name else self.config['NAME']
        self.sessions = []
        self.clients = []
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self._service = None
        self._sshd = None
        self._httpd = None
        self._command_queue = None
        self._replay_queue = None
        self._command_recorder = None
        self._replay_recorder = None

    @property
    def service(self):
        if self._service is None:
            self._service = AppService(self)
        return self._service

    @property
    def sshd(self):
        if self._sshd is None:
            self._sshd = SSHServer(self)
        return self._sshd

    @property
    def httpd(self):
        if self._httpd is None:
            self._httpd = HttpServer(self)
        return self._httpd

    def make_logger(self):
        create_logger(self)

    # Todo: load some config from server like replay and common upload
    def load_extra_conf_from_server(self):
        pass

    def initial_queue(self):
        logger.debug("Initial app queue")
        queue_size = int(self.config['QUEUE_MAX_SIZE'])
        # Todo: For other queue
        if self.config['QUEUE_ENGINE'] == 'memory':
            self._command_queue = MemoryQueue(queue_size)
            self._replay_queue = MemoryQueue(queue_size)
        else:
            self._command_queue = MemoryQueue(queue_size)
            self._replay_queue = MemoryQueue(queue_size)

    def initial_recorder(self):
        if self.config['REPLAY_STORE_ENGINE'] == 'server':
            self._replay_recorder = ServerReplayRecorder(self)
        else:
            self._replay_recorder = ServerReplayRecorder(self)

        if self.config['COMMAND_STORE_ENGINE'] == 'server':
            self._command_recorder = ServerCommandRecorder(self)
        else:
            self._command_recorder = ServerCommandRecorder(self)

    def keep_push_record(self):
        threads = []

        def push_command(q, callback, size=10):
            while not self.stop_evt.is_set():
                data_set = q.mget(size)
                callback(data_set)

        def push_replay(q, callback, size=10):
            while not self.stop_evt.is_set():
                data_set = q.mget(size)
                callback(data_set)

        for i in range(self.config['MAX_PUSH_THREADS']):
            t = threading.Thread(target=push_command, args=(
                self._command_queue, self._command_recorder.record_command,
            ))
            threads.append(t)
            t = threading.Thread(target=push_replay, args=(
                self._replay_queue, self._replay_recorder.record_replay,
            ))
            threads.append(t)

        for t in threads:
            t.start()
            logger.info("Start push record process: {}".format(t))

    def bootstrap(self):
        self.make_logger()
        self.initial_queue()
        self.initial_recorder()
        self.service.initial()
        self.load_extra_conf_from_server()
        self.keep_push_record()
        self.keep_heartbeat()
        self.monitor_sessions()

    def heartbeat(self):
        _sessions = [s.to_json() for s in self.sessions]
        tasks = self.service.terminal_heartbeat(_sessions)
        if tasks:
            self.handle_task(tasks)
        logger.info("Command queue size: {}".format(self._command_queue.qsize()))
        logger.info("Replay queue size: {}".format(self._replay_queue.qsize()))

    def keep_heartbeat(self):
        def func():
            while not self.stop_evt.is_set():
                self.heartbeat()
                time.sleep(self.config["HEARTBEAT_INTERVAL"])

        thread = threading.Thread(target=func)
        thread.start()

    def monitor_sessions(self):
        interval = self.config["HEARTBEAT_INTERVAL"]

        def func():
            while not self.stop_evt.is_set():
                for s in self.sessions:
                    if not s.stop_evt.is_set():
                        continue
                    if s.date_finished is None:
                        self.remove_session(s)
                        continue
                    delta = datetime.datetime.now() - s.date_finished
                    if delta > datetime.timedelta(seconds=interval*5):
                        self.remove_session(s)
                time.sleep(interval)

        thread = threading.Thread(target=func)
        thread.start()

    def handle_task(self, tasks):
        pass

    def run_forever(self):
        self.bootstrap()
        print(time.ctime())
        print('Coco version {}, more see https://www.jumpserver.org'.format(__version__))
        print('Quit the server with CONTROL-C.')

        try:
            if self.config["SSHD_PORT"] != 0:
                self.run_sshd()

            if self.config['HTTPD_PORT'] != 0:
                self.run_httpd()

            self.stop_evt.wait()
        except KeyboardInterrupt:
            self.stop_evt.set()
            self.shutdown()

    def run_sshd(self):
        thread = threading.Thread(target=self.sshd.run, args=())
        thread.daemon = True
        thread.start()

    def run_httpd(self):
        thread = threading.Thread(target=self.httpd.run, args=())
        thread.daemon = True
        thread.start()

    def shutdown(self):
        for client in self.clients:
            self.remove_client(client)
        time.sleep(1)
        self.stop_evt.set()
        self.sshd.shutdown()
        self.httpd.shutdown()
        logger.info("Grace shutdown the server")

    def add_client(self, client):
        with self.lock:
            self.clients.append(client)
            logger.info("New client {} join, total {} now".format(client, len(self.clients)))

    def remove_client(self, client):
        with self.lock:
            try:
                self.clients.remove(client)
                logger.info("Client {} leave, total {} now".format(client, len(self.clients)))
                client.close()
                del client
            except:
                pass

    def add_session(self, session):
        with self.lock:
            self.sessions.append(session)
            self.put_command_start_queue(session)
            self.put_replay_done_queue(session)
            self.heartbeat()

    def remove_session(self, session):
        with self.lock:
            logger.info("Remove session: {}".format(session))
            self.sessions.remove(session)
            self.put_command_done_queue(session)
            self.put_replay_done_queue(session)
            self.heartbeat()

    def put_replay_queue(self, session, data):
        logger.debug("Put replay data: {} {}".format(session, data))
        self._replay_queue.put((
            session.id, data, time.time()
        ))

    def put_replay_start_queue(self, session):
        self._replay_queue.put((
            session.id, START_SENTINEL, time.time()
        ))

    def put_replay_done_queue(self, session):
        self._replay_queue.put((
            session.id, DONE_SENTINEL, time.time()
        ))

    def put_command_queue(self, session, _input, _output):
        logger.debug("Put command data: {} {} {}".format(session, _input, _output))
        self._command_queue.put((
            session.id, _input[:128], _output[:1024], session.client.user.username,
            session.server.asset.hostname, session.server.system_user.username,
            time.time()
        ))

    def put_command_start_queue(self, session):
        self._command_queue.put((
            session.id, START_SENTINEL, START_SENTINEL,
            session.client.user.username,
            session.server.asset.hostname,
            session.server.system_user.username,
            time.time()
        ))

    def put_command_done_queue(self, session):
        self._command_queue.put((
            session.id, DONE_SENTINEL, DONE_SENTINEL,
            session.client.user.username,
            session.server.asset.hostname,
            session.server.system_user.username,
            time.time()
        ))

