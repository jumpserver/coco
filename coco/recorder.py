#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import abc
import threading
import time
import os
import gzip
import json
import shutil

import jms_storage

from .utils import get_logger
from .alignment import MemoryQueue

logger = get_logger(__file__)
BUF_SIZE = 1024


class Singleton(type):
    def __init__(cls, *args, **kwargs):
        cls.__instance = None
        super().__init__(*args, **kwargs)

    def __call__(cls, *args, **kwargs):
        if cls.__instance is None:
            cls.__instance = super().__call__(*args, **kwargs)
            return cls.__instance
        else:
            return cls.__instance


class ReplayRecorder(metaclass=abc.ABCMeta):
    def __init__(self, app, session=None):
        self.app = app
        self.session = session

    @abc.abstractmethod
    def record(self, data):
        """
        记录replay数据
        :param data: 数据 {
            "session": "",
            "data": "",
            "timestamp": ""
        }
        :return:
        """

    @abc.abstractmethod
    def session_start(self, session_id):
        print("Session start: {}".format(session_id))
        pass

    @abc.abstractmethod
    def session_end(self, session_id):
        print("Session end: {}".format(session_id))
        pass


class CommandRecorder:
    def __init__(self, app, session=None):
        self.app = app
        self.session = session

    def record(self, data):
        """
        :param data: 数据 {
            "session":
            "input":
            "output":
            "user":
            "asset":
            "system_user":
            "timestamp":
        }
        :return:
        """

    def session_start(self, session_id):
        print("Session start: {}".format(session_id))
        pass

    def session_end(self, session_id):
        print("Session end: {}".format(session_id))
        pass


class ServerReplayRecorder(ReplayRecorder):
    def __init__(self, app):
        super().__init__(app)
        self.file = None

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
        # Todo: <liuzheng712@gmail.com>
        if len(data['data']) > 0:
            # print(json.dumps(
            #     data['data'].decode('utf-8', 'replace')))
            self.file.write(
                '"' + str(data['timestamp'] - self.starttime) + '":' + json.dumps(
                    data['data'].decode('utf-8', 'replace')) + ',')

    def session_start(self, session_id):
        self.starttime = time.time()
        self.file = open(os.path.join(
            self.app.config['LOG_DIR'], session_id + '.replay'
        ), 'a')
        self.file.write('{')

    def session_end(self, session_id):
        self.file.write('"0":""}')
        self.file.close()
        with open(os.path.join(self.app.config['LOG_DIR'], session_id + '.replay'), 'rb') as f_in, \
                gzip.open(os.path.join(self.app.config['LOG_DIR'], session_id + '.replay.gz'), 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        if self.upload_replay(session_id):
            logger.info("Succeed to push {}'s {}".format(session_id, "record"))
        else:
            logger.error("Failed to push {}'s {}".format(session_id, "record"))
        self.upload_replay(session_id)

    def upload_replay(self, session_id):
        configs = self.app.service.load_config_from_server()
        logger.debug("upload_replay print config: {}".format(configs))
        self.client = jms_storage.init(configs["REPLAY_STORAGE"])
        if not self.client:
            self.client = jms_storage.jms(self.app.service)
        if self.push_storage(3, session_id):
            if self.finish_replay(3, session_id):
                return True
            else:
                return False
        else:
            return False

    def push_to_storage(self, session_id):
        return self.client.upload_file(
            os.path.join(self.app.config['LOG_DIR'], session_id + '.replay.gz'),
            time.strftime('%Y-%m-%d', time.localtime(self.starttime)) + '/' + session_id + '.replay.gz')

    def push_storage(self, times, session_id):
        if times > 0:
            if self.push_to_storage(session_id):
                logger.info("success push session: {}'s replay log to storage ".format(session_id))
                return True
            else:
                logger.error(
                    "failed report session {}'s replay log to storage, try  {} times".format(session_id, times))
                return self.push_storage(times - 1, session_id)
        else:
            logger.error("failed report session {}'s replay log storage, try to push to local".format(session_id))
            if self.client.type() == 'jms':
                return False
            else:
                self.client = jms_storage.jms(self.app.service)
                return self.push_storage(3, session_id)

    def finish_replay(self, times, session_id):
        if times > 0:
            if self.app.service.finish_replay(session_id):
                logger.info("success report session {}'s replay log ".format(session_id))
                return True
            else:
                logger.error("failed report session {}'s replay log, try {} times".format(session_id, times))
                return self.finish_replay(times - 1, session_id)
        else:
            logger.error("failed report session {}'s replay log".format(session_id))
            return False

    # def __del__(self):
    #     print("GC: Server replay recorder has been gc")
    #     del self.file


class ServerCommandRecorder(CommandRecorder, metaclass=Singleton):
    batch_size = 10
    timeout = 5
    no = 0

    def __init__(self, app):
        super().__init__(app)
        self.queue = MemoryQueue()
        self.stop_evt = threading.Event()
        self.push_to_server_async()
        self.__class__.no += 1

    def record(self, data):
        if data and data['input']:
            data['input'] = data['input'][:128]
            data['output'] = data['output'][:1024]
            data['timestamp'] = int(data['timestamp'])
            self.queue.put(data)

    def push_to_server_async(self):
        def func():
            while not self.stop_evt.is_set():
                data_set = self.queue.mget(self.batch_size, timeout=self.timeout)
                logger.debug("<Session command recorder {}> queue size: {}".format(
                    self.no, self.queue.qsize())
                )
                if not data_set:
                    continue
                logger.debug("Send {} commands to server".format(len(data_set)))
                ok = self.app.service.push_session_command(data_set)
                if not ok:
                    self.queue.mput(data_set)

        thread = threading.Thread(target=func)
        thread.daemon = True
        thread.start()

    def session_start(self, session_id):
        pass

    def session_end(self, session_id):
        pass

    # def __del__(self):
    #     print("GC: Session command storage has been gc")


class ESCommandRecorder(CommandRecorder, metaclass=Singleton):
    batch_size = 10
    timeout = 5
    no = 0
    default_hosts = ["http://localhost"]

    def __init__(self, app):
        super().__init__(app)
        self.queue = MemoryQueue()
        self.stop_evt = threading.Event()
        self.push_to_es_async()
        self.__class__.no += 1
        self.store = jms_storage.ESStore(app.config["COMMAND_STORAGE"].get("HOSTS", self.default_hosts))
        if not self.store.ping():
            raise AssertionError("ESCommand storage init error")

    def record(self, data):
        if data and data['input']:
            data['input'] = data['input'][:128]
            data['output'] = data['output'][:1024]
            data['timestamp'] = int(data['timestamp'])
            self.queue.put(data)

    def push_to_es_async(self):
        def func():
            while not self.stop_evt.is_set():
                data_set = self.queue.mget(self.batch_size,
                                           timeout=self.timeout)
                logger.debug(
                    "<Session command recorder {}> queue size: {}".format(
                        self.no, self.queue.qsize())
                )
                if not data_set:
                    continue
                logger.debug("Send {} commands to server".format(len(data_set)))
                ok = self.store.bulk_save(data_set)
                if not ok:
                    self.queue.mput(data_set)

        thread = threading.Thread(target=func)
        thread.daemon = True
        thread.start()

    def session_start(self, session_id):
        pass

    def session_end(self, session_id):
        pass

    # def __del__(self):
    #     print("GC: ES command storage has been gc".format(self))


def get_command_recorder_class(config):
    command_storage = config["COMMAND_STORAGE"]
    storage_type = command_storage.get('TYPE')

    if storage_type == "elasticsearch":
        return ESCommandRecorder
    else:
        return ServerCommandRecorder

#
# def get_replay_recorder_class(config):
#     ServerReplayRecorder.client = jms_storage.init(config["REPLAY_STORAGE"])
#     return ServerReplayRecorder
