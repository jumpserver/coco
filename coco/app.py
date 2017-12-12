#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import datetime
import os
import time
import threading
import logging

from jms.service import AppService

from .config import Config
from .sshd import SSHServer
from .httpd import HttpServer
from .logging import create_logger
from .queue import get_queue
from .record import get_recorder, START_SENTINEL, END_SENTINEL
from .tasks import TaskHandler


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
        'ASSET_LIST_SORT_BY': 'hostname',  # hostname, ip
        'SSH_PASSWORD_AUTH': True,
        'SSH_PUBLIC_KEY_AUTH': True,
        'HEARTBEAT_INTERVAL': 5,
        'MAX_CONNECTIONS': 500,
        'ADMINS': '',
        'REPLAY_RECORD_ENGINE': 'server',   # local, server
        'COMMAND_RECORD_ENGINE': 'server',  # local, server, elasticsearch(not yet)
        'QUEUE_ENGINE': 'memory',
        'QUEUE_MAX_SIZE': 0,
        'MAX_PUSH_THREADS': 5,
        'MAX_RECORD_INPUT_LENGTH': 128,
        'MAX_RECORD_OUTPUT_LENGTH': 1024,
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
        self._replay_queue = None
        self._command_queue = None
        self._replay_recorder = None
        self._command_recorder = None
        self._task_handler = None

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

    @property
    def task_handler(self):
        if self._task_handler is None:
            self._task_handler = TaskHandler(self)
        return self._task_handler

    def make_logger(self):
        create_logger(self)

    # Todo: load some config from server like replay and common upload
    def load_extra_conf_from_server(self):
        pass

    def initial_queue(self):
        self._replay_queue, self._command_queue = get_queue(self.config)

    def initial_recorder(self):
        self._replay_recorder, self._command_recorder = get_recorder(self)

    def bootstrap(self):
        self.make_logger()
        self.service.initial()
        self.load_extra_conf_from_server()
        self.initial_queue()
        self.initial_recorder()
        self.keep_heartbeat()
        self.keep_push_record()
        self.monitor_sessions()

    def heartbeat(self):
        _sessions = [s.to_json() for s in self.sessions]
        tasks = self.service.terminal_heartbeat(_sessions)
        if tasks:
            self.handle_task(tasks)
        if tasks is False:
            return False
        else:
            return True

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

    def keep_push_record(self):
        threads = []

        def worker(q, callback, size=10):
            while not self.stop_evt.is_set():
                data_set = q.mget(size)
                if data_set and not callback(data_set):
                    q.mput(data_set)

        for i in range(self.config['MAX_PUSH_THREADS']):
            t = threading.Thread(target=worker, args=(
                self._command_queue, self._command_recorder.record_command,
            ))
            threads.append(t)
            t = threading.Thread(target=worker, args=(
                self._replay_queue, self._replay_recorder.record_replay,
            ))
            threads.append(t)

        for t in threads:
            t.start()
            logger.info("Start push record process: {}".format(t))

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
            self.heartbeat()
            self.put_command_start_queue(session)
            self.put_replay_start_queue(session)

    def remove_session(self, session):
        with self.lock:
            logger.info("Remove session: {}".format(session))
            for i in range(10):
                if self.heartbeat():
                    self.sessions.remove(session)
                    self.put_command_done_queue(session)
                    self.put_replay_done_queue(session)
                    break
                else:
                    time.sleep(1)

    def put_replay_queue(self, session, data):
        logger.debug("Put replay data: {} {}".format(session, data))
        self._replay_queue.put({
            "session": session.id,
            "data": data,
            "timestamp": time.time()
        })

    def put_replay_start_queue(self, session):
        self._replay_queue.put({
            "session": session.id,
            "data": START_SENTINEL,
            "timestamp": time.time()
        })

    def put_replay_done_queue(self, session):
        self._replay_queue.put({
            "session": session.id,
            "data": END_SENTINEL,
            "timestamp": time.time()
        })

    def put_command_queue(self, session, _input, _output):
        logger.debug("Put command data: {} {} {}".format(session, _input, _output))
        if not _input:
            return
        self._command_queue.put({
            "session": session.id,
            "input": _input[:128],
            "output": _output[:1024],
            "user": session.client.user.username,
            "asset": session.server.asset.hostname,
            "system_user": session.server.system_user.username,
            "timestamp": int(time.time())
        })

    def put_command_start_queue(self, session):
        self._command_queue.put({
            "session": session.id,
            "input": START_SENTINEL,
            "output": START_SENTINEL,
            "user": session.client.user.username,
            "asset": session.server.asset.hostname,
            "system_user": session.server.system_user.username,
            "timestamp": int(time.time())
        })

    def put_command_done_queue(self, session):
        self._command_queue.put({
            "session": session.id,
            "input": END_SENTINEL,
            "output": END_SENTINEL,
            "user": session.client.user.username,
            "asset": session.server.asset.hostname,
            "system_user": session.server.system_user.username,
            "timestamp": int(time.time())
        })
