#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import abc
import threading
import time
import os
import gzip
import json
from copy import deepcopy

import jms_storage

from .config import config
from .utils import get_logger, Singleton
from .struct import MemoryQueue
from .ctx import app_service

logger = get_logger(__file__)
BUF_SIZE = 1024


class ReplayRecorder(metaclass=abc.ABCMeta):
    time_start = None
    storage = None

    def __init__(self):
        super().__init__()
        self.file = None
        self.file_path = None
        self.get_storage()

    def record(self, data):
        """
        :param data:
        [{
            "session": session.id,
            "data": data,
            "timestamp": time.time()
        },...]
        :return:
        """
        if len(data['data']) > 0:
            timedelta = data['timestamp'] - self.time_start
            data = json.dumps(data['data'].decode('utf-8', 'replace'))
            self.file.write('"{}":{},'.format(timedelta, data))

    def session_start(self, session_id):
        self.time_start = time.time()
        filename = session_id + '.replay.gz'
        self.file_path = os.path.join(config['LOG_DIR'], filename)
        self.file = gzip.open(self.file_path, 'at')
        self.file.write('{')

    def session_end(self, session_id):
        self.file.write('"0":""}')
        self.file.close()
        self.upload_replay(session_id)

    def get_storage(self):
        conf = deepcopy(config["REPLAY_STORAGE"])
        conf["SERVICE"] = app_service
        self.storage = jms_storage.get_object_storage(conf)

    def upload_replay(self, session_id, times=3):
        if times < 1:
            if self.storage.type == 'jms':
                return False
            else:
                self.storage = jms_storage.JMSReplayStorage(
                    {"SERVICE": app_service}
                )
                self.upload_replay(session_id, times=3)

        ok, msg = self.push_to_storage(session_id)
        if not ok:
            msg = 'Failed push replay file {}: {}, try again {}'.format(
                session_id, msg, times
            )
            logger.warn(msg)
            self.upload_replay(session_id, times-1)
        else:
            msg = 'Success push replay file: {}'.format(session_id)
            logger.info(msg)
            self.finish_replay(3, session_id)
            os.unlink(self.file_path)
            return True

    def push_to_storage(self, session_id):
        dt = time.strftime('%Y-%m-%d', time.localtime(self.time_start))
        target = dt + '/' + session_id + '.replay.gz'
        return self.storage.upload(self.file_path, target)

    def finish_replay(self, times, session_id):
        if times < 1:
            logger.error(
                "Failed finished session {}'s replay".format(session_id)
            )
            return False

        if app_service.finish_replay(session_id):
            logger.info(
                "Success finish session {}'s replay ".format(session_id)
            )
            return True
        else:
            msg = "Failed finish session {}'s replay, try {} times"
            logger.error(msg.format(session_id, times))
            return self.finish_replay(times - 1, session_id)


class CommandRecorder(metaclass=Singleton):
    batch_size = 10
    timeout = 5
    no = 0
    storage = None

    def __init__(self):
        super().__init__()
        self.queue = MemoryQueue()
        self.stop_evt = threading.Event()
        self.push_to_server_async()
        self.get_storage()

    def record(self, data):
        if data and data['input']:
            data['input'] = data['input'][:128]
            data['output'] = data['output'][:1024]
            data['timestamp'] = int(data['timestamp'])
            self.queue.put(data)

    def get_storage(self):
        conf = deepcopy(config["COMMAND_STORAGE"])
        conf['SERVICE'] = app_service
        self.storage = jms_storage.get_log_storage(conf)

    def push_to_server_async(self):
        def func():
            while not self.stop_evt.is_set():
                data_set = self.queue.mget(self.batch_size, timeout=self.timeout)
                size = self.queue.qsize()
                if size > 0:
                    logger.debug("Session command remain push: {}".format(size))
                if not data_set:
                    continue
                logger.debug("Send {} commands to server".format(len(data_set)))
                ok = self.storage.bulk_save(data_set)
                if not ok:
                    self.queue.mput(data_set)

        thread = threading.Thread(target=func)
        thread.daemon = True
        thread.start()

    def session_start(self, session_id):
        pass

    def session_end(self, session_id):
        pass


def get_command_recorder():
    return CommandRecorder()


def get_replay_recorder():
    return ReplayRecorder()


def get_recorder():
    return get_command_recorder(), get_replay_recorder()