# -*- coding: utf-8 -*-
#

import queue


class MultiQueueMixin:
    def mget(self, size=1, block=True, timeout=5):
        items = []
        for i in range(size):
            try:
                items.append(self.get(block=block, timeout=timeout))
            except queue.Empty:
                break
        return items


class MemoryQueue(MultiQueueMixin, queue.Queue):
    pass
