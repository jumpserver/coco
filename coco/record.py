# -*- coding: utf-8 -*-
#

import abc
import multiprocessing
import threading
import time
import datetime
import socket
import os
import logging


logger = logging.getLogger(__file__)
BUF_SIZE = 1024


class Recorder(metaclass=abc.ABCMeta):

    def __init__(self, app, session):
        self.app = app
        self.session = session
        self.replay_queue = multiprocessing.Queue()
        self.command_queue = multiprocessing.Queue()
        self.stop_evt = multiprocessing.Event()

    @abc.abstractmethod
    def record_replay(self):
        pass

    @abc.abstractmethod
    def record_command(self, _input, _output):
        pass


class FileRecorder(Recorder):
    def record_replay(self):
        parent, child = socket.socketpair()
        self.session.add_watcher(parent)
        session_dir = self.app.config["SESSION_DIR"]

        with open(os.path.join(session_dir, session.id + ".rec"), 'wb') as dataf, \
                open(os.path.join(session_dir, session.id + ".time"), "w") as timef:
            dataf.write("Script started on {}\n".format(time.asctime()).encode("utf-8"))

            while not self.stop_evt.is_set():
                start_t = time.time()
                data = child.recv(BUF_SIZE)
                end_t = time.time()
                size = len(data)
                if size == 0:
                    break
                timef.write("%.4f %s\n" % (end_t - start_t, size))
                dataf.write(data)
            dataf.write("Script done on {}\n".format(time.asctime()).encode("utf-8"))

    def record_command(self, _input, _output):
        pass


class SessionReplay(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def write_meta(self, meta):
        pass

    @abc.abstractmethod
    def write_data(self, data):
        pass

    @abc.abstractmethod
    def done(self):
        pass


class SessionCommand(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def write(self, cmd, output):
        pass


class FileSessionReplay(SessionReplay):

    def __init__(self, dataf, metaf):
        self.dataf = dataf
        self.metaf = metaf
        self.playing = True

    def write_data(self, data):
        self.dataf.write(data)

    def write_meta(self, meta):
        self.metaf.write(meta)

    def replay(self, sock):
        sock.send(self.dataf.readline())
        for l in self.metaf:
            if not self.playing:
                break
            t, size = float(l.split()[0]), int(l.split()[1])
            data = self.dataf.read(size)
            time.sleep(t)
            sock.send(data)
        sock.send("Replay session end")

    def done(self):
        pass


class FileSessionCommand(SessionCommand):

    def __init__(self, f):
        self.f = f

    def write(self, cmd, output):
        self.f.write("{}\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.f.write("$ {}\n".format(cmd))
        self.f.write("{}\n\n".format(output))

    def done(self):
        pass

