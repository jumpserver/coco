#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import queue
import socket


class MultiQueueMixin:
    def mget(self, size=1, block=True, timeout=5):
        items = []
        for i in range(size):
            try:
                items.append(self.get(block=block, timeout=timeout))
            except queue.Empty:
                break
        return items

    def mput(self, data_set):
        for i in data_set:
            self.put(i)


class MemoryQueue(MultiQueueMixin, queue.Queue):
    pass


class SizedList(list):
    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self.size = 0
        super().__init__()

    def append(self, b):
        if self.maxsize == 0 or self.size < self.maxsize:
            super().append(b)
            self.size += len(b)

    def clean(self):
        self.size = 0
        del self[:]


class SelectEvent:
    def __init__(self):
        self.p1, self.p2 = socket.socketpair()

    def set(self):
        self.p2.send(b'0')

    def fileno(self):
        return self.p1.fileno()

    def __getattr__(self, item):
        return getattr(self.p1, item)
