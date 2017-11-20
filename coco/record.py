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

    @property
    def session_dir(self):
        session_dir = os.path.join(
            self.app.config["SESSION_DIR"],
            self.session.date_created.strftime("%Y-%m-%d")
        )
        if not os.path.isdir(session_dir):
            os.mkdir(session_dir)
        return session_dir

    @property
    def data_f(self):
        filename = os.path.join(self.session_dir, str(self.session.id) + ".rec")
        try:
            f = open(filename, 'wb')
        except IOError:
            logger.error("Failed open file {} in recorder".format(filename))
            raise
        return f

    @property
    def time_f(self):
        filename = os.path.join(self.session_dir, str(self.session.id) + ".time")
        try:
            f = open(filename, 'w')
        except IOError:
            logger.error("Failed open file {} in recorder".format(filename))
            raise
        return f

    @property
    def cmd_f(self):
        filename = os.path.join(self.session_dir, str(self.session.id) + ".cmd")
        try:
            f = open(filename, "w")
        except IOError:
            logger.error("Failed open file {} in recorder".format(filename))
            raise
        return f

    def record_replay(self, now, timedelta, size, data):
        self.time_f.write("%.4f %s\n" % (timedelta, size))
        self.data_f.write(data)

    def record_command(self, now, _input, _output):
        self.cmd_f.write("{}\n".format(now.strftime("%Y-%m-%d %H:%M:%S")))
        self.cmd_f.write("$ {}\n".format(_input))
        self.cmd_f.write("{}\n\n".format(_output))

    def start(self):
        self.data_f.write("Session started on {}\n".format(time.asctime()).encode("utf-8"))

    def done(self):
        self.data_f.write("Session done on {}\n".format(time.asctime()).encode("utf-8"))
        for f in [self.data_f, self.time_f, self.cmd_f]:
            try:
                f.close()
            except IOError:
                pass


# class FileSessionReplay(SessionReplay):
#
#     def __init__(self, dataf, metaf):
#         self.dataf = dataf
#         self.metaf = metaf
#         self.playing = True
#
#     def write_data(self, data):
#         self.dataf.write(data)
#
#     def write_meta(self, meta):
#         self.metaf.write(meta)
#
#     def replay(self, sock):
#         sock.send(self.dataf.readline())
#         for l in self.metaf:
#             if not self.playing:
#                 break
#             t, size = float(l.split()[0]), int(l.split()[1])
#             data = self.dataf.read(size)
#             time.sleep(t)
#             sock.send(data)
#         sock.send("Replay session end")
#
#     def done(self):
#         pass
#
#
# class FileSessionCommand(SessionCommand):
#
#     def __init__(self, f):
#         self.f = f
#
#     def write(self, cmd, output):
#         self.f.write("{}\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
#         self.f.write("$ {}\n".format(cmd))
#         self.f.write("{}\n\n".format(output))
#
#     def done(self):
#         pass

