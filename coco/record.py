# -*- coding: utf-8 -*-
#

import abc
import time
import os
import logging


logger = logging.getLogger(__file__)
BUF_SIZE = 1024


class Recorder(metaclass=abc.ABCMeta):

    def __init__(self, app, session):
        self.app = app
        self.session = session

    @abc.abstractmethod
    def record_replay(self, now, timedelta, size, data):
        pass

    @abc.abstractmethod
    def record_command(self, now, _input, _output):
        pass

    @abc.abstractmethod
    def start(self):
        pass

    @abc.abstractmethod
    def done(self):
        pass


class FileRecorder(Recorder):

    def __init__(self, app, session):
        super().__init__(app, session)
        self.data_f = None
        self.time_f = None
        self.cmd_f = None
        self.prepare_file()

    def prepare_file(self):
        session_dir = os.path.join(
            self.app.config["SESSION_DIR"],
            self.session.date_created.strftime("%Y-%m-%d")
        )
        if not os.path.isdir(session_dir):
            os.mkdir(session_dir)

        filename = os.path.join(session_dir, str(self.session.id))
        data_filename = filename + ".rec"
        time_filename = filename + ".time"
        cmd_filename = filename + ".cmd"

        try:
            self.data_f = open(data_filename, "wb")
            self.time_f = open(time_filename, "w")
            self.cmd_f = open(cmd_filename, "w")
        except IOError as e:
            logger.debug(e)
            self.done()

    def record_replay(self, now, timedelta, size, data):
        logger.debug("File recorder replay: ({},{},{})".format(timedelta, size, data))
        self.time_f.write("{} {}\n".format(timedelta, size))
        self.data_f.write(data)

    def record_command(self, now, _input, _output):
        logger.debug("File recorder command: ({},{})".format(_input, _output))
        self.cmd_f.write("{}\n".format(now.strftime("%Y-%m-%d %H:%M:%S")))
        self.cmd_f.write("$ {}\n".format(_input))
        self.cmd_f.write("{}\n\n".format(_output))
        self.cmd_f.flush()

    def start(self):
        logger.debug("Session {} start".format(self.session.id))
        self.data_f.write("Session {} started on {}\n".format(self.session.id, time.asctime()).encode("utf-8"))

    def done(self):
        logger.debug("Session {} record done".format(self.session.id))
        self.data_f.write("Session {} done on {}\n".format(self.session.id, time.asctime()).encode("utf-8"))
        for f in [self.data_f, self.time_f, self.cmd_f]:
            try:
                f.close()
            except IOError:
                pass




