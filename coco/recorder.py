#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import threading
import datetime
import time
import os
import json
from copy import deepcopy

import jms_storage

from .conf import config
from .utils import get_logger, gzip_file
from .struct import MemoryQueue
from .service import app_service

logger = get_logger(__file__)
BUF_SIZE = 1024


class ReplayRecorder(object):
    time_start = None
    target = None
    storage = None
    session_id = None
    filename = None
    file = None
    file_path = None
    filename_gz = None
    file_gz_path = None

    def __init__(self):
        self.get_storage()

    def get_storage(self):
        conf = deepcopy(config["REPLAY_STORAGE"])
        conf["SERVICE"] = app_service
        self.storage = jms_storage.get_object_storage(conf)

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
        self.session_id = session_id
        self.filename = session_id
        self.filename_gz = session_id + '.replay.gz'

        date = datetime.datetime.utcnow().strftime('%Y-%m-%d')
        replay_dir = os.path.join(config.REPLAY_DIR, date)
        if not os.path.isdir(replay_dir):
            os.makedirs(replay_dir, exist_ok=True)
        # 录像记录路径
        self.file_path = os.path.join(replay_dir, self.filename)
        # 录像压缩到的路径
        self.file_gz_path = os.path.join(replay_dir, self.filename_gz)
        # 录像上传上去的路径
        self.target = date + '/' + self.filename_gz
        self.file = open(self.file_path, 'at')
        self.file.write('{')

    def session_end(self, session_id):
        self.file.write('"0":""}')
        self.file.close()
        gzip_file(self.file_path, self.file_gz_path)
        self.upload_replay_some_times()

    def upload_replay_some_times(self, times=3):
        # 如果上传OSS、S3失败则尝试上传到服务器
        if times < 1:
            if self.storage.type == 'jms':
                return False
            self.storage = jms_storage.JMSReplayStorage(
                {"SERVICE": app_service}
            )
            self.upload_replay_some_times(times=3)

        ok, msg = self.upload_replay()
        if not ok:
            msg = 'Failed push replay file {}: {}, try again {}'.format(
                self.filename, msg, times
            )
            logger.warn(msg)
            self.upload_replay_some_times(times - 1)
        else:
            msg = 'Success push replay file: {}'.format(self.session_id)
            logger.debug(msg)
            return True

    def upload_replay(self):
        # 如果文件为空就直接删除
        if not os.path.isfile(self.file_gz_path):
            return False, 'Not found the file: {}'.format(self.file_gz_path)
        if os.path.getsize(self.file_gz_path) == 0:
            os.unlink(self.file_gz_path)
            return True, ''
        ok, msg = self.storage.upload(self.file_gz_path, self.target)
        if ok:
            self.finish_replay(3, self.session_id)
            os.unlink(self.file_gz_path)
        return ok, msg

    def finish_replay(self, times, session_id):
        if times < 1:
            logger.error(
                "Failed finished session {}'s replay".format(session_id)
            )
            return False

        if app_service.finish_replay(session_id):
            logger.debug(
                "Success finished session {}'s replay ".format(session_id)
            )
            return True
        else:
            msg = "Failed finished session {}'s replay, try {} times"
            logger.error(msg.format(session_id, times))
            return self.finish_replay(times - 1, session_id)


class CommandRecorder(object):
    batch_size = 10
    timeout = 5
    no = 0
    storage = None
    _cache = []

    def __init__(self):
        super(CommandRecorder, self).__init__()
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
            while True:
                if self.stop_evt.is_set() and self.queue.empty():
                    break
                data_set = self.queue.mget(self.batch_size, timeout=self.timeout)
                size = self.queue.qsize()
                if size > 0:
                    logger.debug("Session command remain push: {}".format(size))
                if not data_set:
                    continue
                logger.debug("Send {} commands to server".format(len(data_set)))
                for i in range(5):
                    ok = self.storage.bulk_save(data_set)
                    if ok:
                        break

        thread = threading.Thread(target=func)
        thread.daemon = True
        thread.start()

    def session_start(self, session_id):
        pass

    def session_end(self, session_id):
        self.stop_evt.set()


def get_command_recorder():
    return CommandRecorder()


def get_replay_recorder():
    return ReplayRecorder()


def get_recorder():
    return get_command_recorder(), get_replay_recorder()