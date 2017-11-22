# -*- coding: utf-8 -*-
#

import abc
import tarfile
import threading
import time
import os
import logging


logger = logging.getLogger(__file__)
BUF_SIZE = 1024


class ReplayRecorder(metaclass=abc.ABCMeta):

    def __init__(self, app, session):
        self.app = app
        self.session = session

    @abc.abstractmethod
    def record_replay(self, now, timedelta, size, data):
        pass

    @abc.abstractmethod
    def start(self):
        pass

    @abc.abstractmethod
    def done(self):
        pass


class CommandRecorder(metaclass=abc.ABCMeta):
    def __init__(self, app, session):
        self.app = app
        self.session = session

    @abc.abstractmethod
    def record_command(self, now, _input, _output):
        pass

    @abc.abstractmethod
    def start(self):
        pass

    @abc.abstractmethod
    def done(self):
        pass


class LocalFileReplayRecorder(ReplayRecorder):

    def __init__(self, app, session):
        super().__init__(app, session)
        self.session_dir = ""
        self.data_filename = ""
        self.time_filename = ""
        self.data_f = None
        self.time_f = None
        self.prepare_file()

    def prepare_file(self):
        self.session_dir = os.path.join(
            self.app.config["SESSION_DIR"],
            self.session.date_created.strftime("%Y-%m-%d"),
            str(self.session.id)
        )
        if not os.path.isdir(self.session_dir):
            os.makedirs(self.session_dir)

        self.data_filename = os.path.join(self.session_dir, "data.txt")
        self.time_filename = os.path.join(self.session_dir, "time.txt")

        try:
            self.data_f = open(self.data_filename, "wb")
            self.time_f = open(self.time_filename, "w")
        except IOError as e:
            logger.debug(e)
            self.done()

    def record_replay(self, now, timedelta, size, data):
        logger.debug("File recorder replay: ({},{},{})".format(timedelta, size, data))
        self.time_f.write("{} {}\n".format(timedelta, size))
        self.data_f.write(data)

    def start(self):
        logger.debug("Session {} start".format(self.session.id))
        self.data_f.write("Session {} started on {}\n".format(self.session.id, time.asctime()).encode("utf-8"))

    def done(self):
        logger.debug("Session {} record done".format(self.session.id))
        self.data_f.write("Session {} done on {}\n".format(self.session.id, time.asctime()).encode("utf-8"))
        for f in (self.data_f, self.time_f):
            try:
                f.close()
            except IOError:
                pass


class LocalFileCommandRecorder(CommandRecorder):
    def __init__(self, app, session):
        super().__init__(app, session)
        self.cmd_f = None
        self.prepare_file()

    def prepare_file(self):
        session_dir = os.path.join(
            self.app.config["SESSION_DIR"],
            self.session.date_created.strftime("%Y-%m-%d"),
            str(self.session.id)
        )
        if not os.path.isdir(session_dir):
            os.makedirs(session_dir)

        cmd_filename = os.path.join(session_dir, "cmd.txt")
        try:
            self.cmd_f = open(cmd_filename, "w")
        except IOError as e:
            logger.debug(e)
            self.done()

    def record_command(self, now, _input, _output):
        logger.debug("File recorder command: ({},{})".format(_input, _output))
        self.cmd_f.write("{}\n".format(now.strftime("%Y-%m-%d %H:%M:%S")))
        self.cmd_f.write("$ {}\n".format(_input))
        self.cmd_f.write("{}\n\n".format(_output))
        self.cmd_f.flush()

    def start(self):
        pass

    def done(self):
        pass


class ServerReplayRecorder(LocalFileReplayRecorder):

    def done(self):
        super().done()
        self.push_records()

    def archive_replay(self):
        filename = os.path.join(self.session_dir, "archive.tar.bz2")
        logger.debug("Start archive log: {}".format(filename))
        tar = tarfile.open(filename, "w:bz2")
        os.chdir(self.session_dir)
        time_filename = os.path.basename(self.time_filename)
        data_filename = os.path.basename(self.data_filename)
        for i in (time_filename, data_filename):
            tar.add(i)
        tar.close()
        return filename

    def push_replay_record(self, archive):
        logger.debug("Start push replay record to server")
        return self.app.service.push_session_replay(archive, str(self.session.id))

    def push_records(self):
        def func():
            archive = self.archive_replay()
            result = self.push_replay_record(archive)
            if not result:
                logger.error("Push replay error")

        thread = threading.Thread(target=func)
        thread.start()
