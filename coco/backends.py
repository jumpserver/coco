#!/usr/bin/env python3
# ~*~ coding: utf-8 ~*~
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty


class QueueMultiMixin(object):
    def mget(self, size=1, block=True, timeout=5):
        items = []
        for i in range(size):
            try:
                items.append(self.get(block=block, timeout=timeout))
            except Empty:
                break
        return items


class MemoryQueue(Queue, QueueMultiMixin):
    pass
