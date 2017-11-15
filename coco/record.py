# -*- coding: utf-8 -*-
#

import abc
import datetime
import time


class SessionReplay(metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def write_meta(self, meta):
        pass

    @abc.abstractmethod
    def write_data(self, data):
        pass

    @abc.abstractmethod
    def replay(self, sock):
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


class FileSessionCommand(SessionCommand):

    def __init__(self, f):
        self.f = f

    def write(self, cmd, output):
        self.f.write("{}\n".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.f.write("$ {}\n".format(cmd))
        self.f.write("{}\n\n".format(output))

