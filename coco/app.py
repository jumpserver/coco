#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import datetime
import os
import time
import threading
import json
import signal
import copy
from collections import defaultdict

from .conf import config
from .sshd import SSHServer
from .httpd import HttpServer
from .tasks import TaskHandler
from .utils import get_logger, ugettext as _, ignore_error
from .service import app_service
from .recorder import get_replay_recorder
from .session import Session
from .models import Connection


__version__ = '1.4.7'

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = get_logger(__file__)


class Coco:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self._service = None
        self._sshd = None
        self._httpd = None
        self.replay_recorder_class = None
        self.command_recorder_class = None
        self._task_handler = None

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

    @staticmethod
    @ignore_error
    def load_extra_conf_from_server():
        configs = app_service.load_config_from_server()
        config.update(configs)

        tmp = copy.deepcopy(configs)
        tmp['HOST_KEY'] = tmp.get('HOST_KEY', '')[32:50] + '...'
        logger.debug("Loading config from server: {}".format(
            json.dumps(tmp)
        ))

    def keep_load_extra_conf(self):
        def func():
            while True:
                self.load_extra_conf_from_server()
                time.sleep(60*10)
        thread = threading.Thread(target=func)
        thread.start()

    def bootstrap(self):
        self.load_extra_conf_from_server()
        self.keep_load_extra_conf()
        self.keep_heartbeat()
        self.monitor_sessions()
        self.monitor_sessions_replay()

    # @ignore_error
    def heartbeat(self):
        sessions = list(Session.sessions.keys())
        # p = psutil.Process(os.getpid())
        # cpu_used = p.cpu_percent(interval=1.0)
        # memory_used = int(p.memory_info().rss / 1024 / 1024)
        # connections = len(p.connections())
        # threads = p.num_threads()
        # session_online = len(sessions)
        data = {
            # "cpu_used": cpu_used,
            # "memory_used": memory_used,
            # "connections": connections,
            # "threads": threads,
            # "boot_time": p.create_time(),
            # "session_online": session_online,
            "sessions": sessions,
        }
        tasks = app_service.terminal_heartbeat(data)

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
                try:
                    self.heartbeat()
                except IndexError as e:
                    logger.error("Unexpected error occur: {}".format(e))
                time.sleep(config["HEARTBEAT_INTERVAL"])
        thread = threading.Thread(target=func)
        thread.start()

    def monitor_sessions_replay(self):
        interval = 60 * 60 * 5
        replay_dir = os.path.join(config.REPLAY_DIR)
        max_try = 5
        upload_failed = defaultdict(int)

        def func():
            while not self.stop_evt.is_set():
                for d in os.listdir(replay_dir):
                    date_path = os.path.join(replay_dir, d)
                    for filename in os.listdir(date_path):
                        suffix = filename.split('.')[-1]
                        if suffix != 'gz':
                            continue
                        session_id = filename.split('.')[0]
                        if len(session_id) != 36:
                            continue

                        full_path = os.path.join(date_path, filename)
                        stat = os.stat(full_path)
                        # 是否是一天前的，因为现在多个coco共享了日志目录，
                        # 不能单纯判断session是否关闭
                        if stat.st_mtime > time.time() - 24*60*60:
                            continue
                        # 失败次数过多
                        if session_id in upload_failed \
                                and upload_failed[session_id] >= max_try:
                            continue
                        recorder = get_replay_recorder()
                        recorder.file_path = full_path
                        recorder.session_id = session_id
                        recorder.target = os.path.join(d, filename)
                        ok, msg = recorder.upload_replay()
                        if ok:
                            upload_failed.pop(session_id, None)
                        else:
                            upload_failed[session_id] += 1
                        time.sleep(1)
                time.sleep(interval)
        thread = threading.Thread(target=func)
        thread.start()

    def monitor_sessions(self):
        interval = config["HEARTBEAT_INTERVAL"]

        def check_session_idle_too_long(s):
            delta = datetime.datetime.utcnow() - s.date_last_active
            max_idle_seconds = config['SECURITY_MAX_IDLE_TIME'] * 60
            if delta.seconds > max_idle_seconds:
                msg = _(
                    "Connect idle more than {} minutes, disconnect").format(
                    config['SECURITY_MAX_IDLE_TIME']
                )
                s.terminate(msg=msg)
                return True

        def func():
            while not self.stop_evt.is_set():
                try:
                    sessions_copy = [s for s in Session.sessions.values()]
                    for s in sessions_copy:
                        # Session 没有正常关闭,
                        if s.closed_unexpected:
                            Session.remove_session(s.id)
                            continue
                        # Session已正常关闭
                        if s.closed:
                            Session.remove_session(s.id)
                        else:
                            check_session_idle_too_long(s)
                except Exception as e:
                    logger.error("Unexpected error occur: {}".format(e))
                time.sleep(interval)
        thread = threading.Thread(target=func)
        thread.start()

    def run_forever(self):
        self.bootstrap()
        print(time.ctime())
        print('Coco version {}, more see https://www.jumpserver.org'.format(__version__))
        print('Quit the server with CONTROL-C.')

        try:
            if config["SSHD_PORT"] != 0:
                self.run_sshd()

            if config['HTTPD_PORT'] != 0:
                self.run_httpd()

            signal.signal(signal.SIGTERM, lambda x, y: self.shutdown())
            self.lock.acquire()
            self.lock.acquire()
        except KeyboardInterrupt:
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
        logger.info("Grace shutdown the server")
        for connection in Connection.connections.values():
            connection.close()
        self.heartbeat()
        self.lock.release()
        self.stop_evt.set()
        self.sshd.shutdown()
        self.httpd.shutdown()
