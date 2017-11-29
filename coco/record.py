# -*- coding: utf-8 -*-
#

import abc
import logging


logger = logging.getLogger(__file__)
BUF_SIZE = 1024

START_SENTINEL = object()
DONE_SENTINEL = object()


class ReplayRecorder(metaclass=abc.ABCMeta):

    def __init__(self, app):
        self.app = app

    @abc.abstractmethod
    def record_replay(self, data_set):
        """
        记录replay数据
        :param data_set: 数据集 [("session", "data", "timestamp"),]
        :return:
        """

        for data in data_set:
            if data[1] is START_SENTINEL:
                data_set.remove(data)
                self.session_start(data[0])

            if data[1] is DONE_SENTINEL:
                data_set.remove(data)
                self.session_done(data[0])

    @abc.abstractmethod
    def session_done(self, session_id):
        pass

    @abc.abstractmethod
    def session_start(self, session_id):
        pass


class CommandRecorder(metaclass=abc.ABCMeta):
    def __init__(self, app):
        self.app = app

    @abc.abstractmethod
    def record_command(self, data_set):
        """
        :param data_set: 数据集
            [("session", "input", "output", "user",
              "asset", "system_user", "timestamp"),]
        :return:
        """
        for data in data_set:
            if data[1] is START_SENTINEL:
                data_set.remove(data)
                self.session_start(data[0])

            if data[1] is DONE_SENTINEL:
                data_set.remove(data)
                self.session_done(data[0])

    @abc.abstractmethod
    def session_start(self, session_id):
        pass

    @abc.abstractmethod
    def session_done(self, session_id):
        pass


class ServerReplayRecorder(ReplayRecorder):

    def record_replay(self, data_set):
        super().record_replay(data_set)
        print(data_set)

    def session_start(self, session_id):
        print("Session {} start".format(session_id))

    def session_done(self, session_id):
        print("Session {} done".format(session_id))


class ServerCommandRecorder(CommandRecorder):

    def record_command(self, data_set):
        super().record_command(data_set)
        print(data_set)

    def session_start(self, session_id):
        print("Session {} start".format(session_id))

    def session_done(self, session_id):
        print("Session {} done".format(session_id))

