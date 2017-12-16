#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import abc
import logging

logger = logging.getLogger(__file__)
BUF_SIZE = 1024

START_SENTINEL = object()
END_SENTINEL = object()


class ReplayRecorder(metaclass=abc.ABCMeta):
    def __init__(self, app):
        self.app = app

    @abc.abstractmethod
    def record_replay(self, data_set):
        """
        记录replay数据
        :param data_set: 数据集 [{"session": "", "data": "", "timestamp": ""},]
        :return:
        """
        for data in data_set:
            if data["data"] is START_SENTINEL:
                data_set.remove(data)
                self.session_start(data["session"])

            if data["data"] is END_SENTINEL:
                data_set.remove(data)
                self.session_end(data["session"])

    @abc.abstractmethod
    def session_start(self, session_id):
        print("Session start")
        pass

    @abc.abstractmethod
    def session_end(self, session_id):
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
            if data["input"] is START_SENTINEL:
                data_set.remove(data)
                self.session_start(data["session"])

            if data["input"] is END_SENTINEL:
                data_set.remove(data)
                self.session_end(data["session"])

    @abc.abstractmethod
    def session_start(self, session_id):
        pass

    @abc.abstractmethod
    def session_end(self, session_id):
        pass


class ServerReplayRecorder(ReplayRecorder):
    filelist = {}

    def record_replay(self, data_set):
        """
        :param data_set:
        [{
            "session": session.id,
            "data": data,
            "timestamp": time.time()
        },...]
        :return:
        """
        # Todo: <liuzheng712@gmail.com>
        super().record_replay(data_set)
        for data in data_set:
            try:
                self.filelist[data["session"]].write(data)
            except IndexError:
                logger.error("session ({})file does not exist!".format(data["session"]))

    def session_start(self, session_id):
        self.filelist[session_id] = open(session_id + '.log', 'a')
        print("When session {} start exec".format(session_id))

    def session_end(self, session_id):
        self.filelist[session_id].close()
        # Todo: upload the file
        print("When session {} end start".format(session_id))


class ServerCommandRecorder(CommandRecorder):
    def record_command(self, data_set):
        if not data_set:
            return True
        super().record_command(data_set)
        return self.app.service.push_session_command(data_set)

    def session_start(self, session_id):
        print("When session {} start exec".format(session_id))

    def session_end(self, session_id):
        print("When session {} end start".format(session_id))


def get_recorder(app):
    replay_engine = app.config["REPLAY_RECORD_ENGINE"]
    command_engine = app.config["COMMAND_RECORD_ENGINE"]

    if replay_engine == "server":
        replay_recorder = ServerReplayRecorder(app)
    else:
        replay_recorder = ServerReplayRecorder(app)

    if command_engine == "server":
        command_recorder = ServerCommandRecorder(app)
    else:
        command_recorder = ServerCommandRecorder(app)

    return replay_recorder, command_recorder
