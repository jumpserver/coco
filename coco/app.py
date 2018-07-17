#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import datetime
import os
import time
import threading
import socket
import json
import signal
import eventlet
from eventlet.debug import hub_prevent_multiple_readers

from jms.service import AppService

from .config import Config
from .sshd import SSHServer
from .httpd import HttpServer
from .logger import create_logger
from .tasks import TaskHandler
from .recorder import ReplayRecorder, CommandRecorder
from .utils import get_logger, register_app, register_service

eventlet.monkey_patch()
hub_prevent_multiple_readers(False)

__version__ = '1.3.3'

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = get_logger(__file__)


class Coco:
    config_class = Config
    default_config = {
        'DEFAULT_NAME': socket.gethostname(),
        'NAME': None,
        'CORE_HOST': 'http://127.0.0.1:8080',
        'DEBUG': True,
        'BIND_HOST': '0.0.0.0',
        'SSHD_PORT': 2222,
        'HTTPD_PORT': 5000,
        'ACCESS_KEY': '',
        'ACCESS_KEY_ENV': 'COCO_ACCESS_KEY',
        'ACCESS_KEY_FILE': os.path.join(BASE_DIR, 'keys', '.access_key'),
        'SECRET_KEY': None,
        'LOG_LEVEL': 'DEBUG',
        'LOG_DIR': os.path.join(BASE_DIR, 'logs'),
        'SESSION_DIR': os.path.join(BASE_DIR, 'sessions'),
        'ASSET_LIST_SORT_BY': 'hostname',  # hostname, ip
        'PASSWORD_AUTH': True,
        'PUBLIC_KEY_AUTH': True,
        'HEARTBEAT_INTERVAL': 5,
        'MAX_CONNECTIONS': 500,
        'ADMINS': '',
        'COMMAND_STORAGE': {'TYPE': 'server'},   # server
        'REPLAY_STORAGE': {'TYPE': 'server'},
    }

    def __init__(self, root_path=None):
        self.root_path = root_path if root_path else BASE_DIR
        self.sessions = []
        self.clients = []
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self._service = None
        self._sshd = None
        self._httpd = None
        self.replay_recorder_class = None
        self.command_recorder_class = None
        self._task_handler = None
        self.config = None
        self.init_config()
        register_app(self)

    def init_config(self):
        self.config = self.config_class(
            self.root_path, defaults=self.default_config
        )

    @property
    def name(self):
        if self.config['NAME']:
            return self.config['NAME']
        else:
            return self.config['DEFAULT_NAME']

    @property
    def service(self):
        if self._service is None:
            self._service = AppService(self)
            register_service(self._service)
        return self._service

    @property
    def sshd(self):
        if self._sshd is None:
            self._sshd = SSHServer()
        return self._sshd

    @property
    def httpd(self):
        if self._httpd is None:
            self._httpd = HttpServer()
        return self._httpd

    @property
    def task_handler(self):
        if self._task_handler is None:
            self._task_handler = TaskHandler()
        return self._task_handler

    def make_logger(self):
        create_logger(self)

    def load_extra_conf_from_server(self):
        configs = self.service.load_config_from_server()
        logger.debug("Loading config from server: {}".format(
            json.dumps(configs)
        ))
        self.config.update(configs)

    @staticmethod
    def new_command_recorder():
        return CommandRecorder()

    @staticmethod
    def new_replay_recorder():
        return ReplayRecorder()

    def bootstrap(self):
        self.make_logger()
        self.service.initial()
        self.load_extra_conf_from_server()
        self.keep_heartbeat()
        self.monitor_sessions()
        self.monitor_sessions_replay()

    def heartbeat(self):
        _sessions = [s.to_json() for s in self.sessions]
        tasks = self.service.terminal_heartbeat(_sessions)
        if tasks:
            self.handle_task(tasks)
        if tasks is False:
            return False
        else:
            return True

    def heartbeat_async(self):
        t = threading.Thread(target=self.heartbeat)
        t.start()

    def handle_task(self, tasks):
        for task in tasks:
            self.task_handler.handle(task)

    def keep_heartbeat(self):
        def func():
            while not self.stop_evt.is_set():
                self.heartbeat()
                time.sleep(self.config["HEARTBEAT_INTERVAL"])

        thread = threading.Thread(target=func)
        thread.start()

    def monitor_sessions_replay(self):
        interval = 10
        recorder = self.new_replay_recorder()
        log_dir = os.path.join(self.config['LOG_DIR'])

        def func():
            while not self.stop_evt.is_set():
                active_sessions = [str(session.id) for session in self.sessions]
                for filename in os.listdir(log_dir):
                    session_id = filename.split('.')[0]
                    full_path = os.path.join(log_dir, filename)

                    if len(session_id) != 36:
                        continue

                    if session_id not in active_sessions:
                        recorder.file_path = full_path
                        ok = recorder.upload_replay(session_id, 1)
                        if not ok and os.path.getsize(full_path) == 0:
                            os.unlink(full_path)
                    time.sleep(1)
                time.sleep(interval)
        thread = threading.Thread(target=func)
        thread.start()

    def monitor_sessions(self):
        interval = self.config["HEARTBEAT_INTERVAL"]

        def func():
            while not self.stop_evt.is_set():
                for s in self.sessions:
                    if not s.stop_evt.is_set():
                        continue
                    if s.date_end is None:
                        self.remove_session(s)
                        continue
                    delta = datetime.datetime.now() - s.date_end
                    if delta > datetime.timedelta(seconds=interval*5):
                        self.remove_session(s)
                time.sleep(interval)

        thread = threading.Thread(target=func)
        thread.start()

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

            signal.signal(signal.SIGTERM, lambda x, y: self.shutdown())
            while True:
                if self.stop_evt.is_set():
                    print("Coco receive term signal, exit")
                    break
                time.sleep(3)
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
        self.heartbeat()
        self.stop_evt.set()
        self.sshd.shutdown()
        self.httpd.shutdown()
        logger.info("Grace shutdown the server")

    def add_client(self, client):
        with self.lock:
            self.clients.append(client)
            logger.info("New client {} join, total {} now".format(
                    client, len(self.clients)
                )
            )

    def remove_client(self, client):
        with self.lock:
            try:
                self.clients.remove(client)
                logger.info("Client {} leave, total {} now".format(
                       client, len(self.clients)
                    )
                )
                client.close()
            except:
                pass

    def add_session(self, session):
        with self.lock:
            self.sessions.append(session)
            self.service.create_session(session.to_json())

    def remove_session(self, session):
        with self.lock:
            try:
                logger.info("Remove session: {}".format(session))
                self.sessions.remove(session)
                self.service.finish_session(session.to_json())
            except ValueError:
                msg = "Remove session: {} fail, maybe already removed"
                logger.warning(msg.format(session))
