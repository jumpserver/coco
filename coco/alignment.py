#!/usr/bin/env python3
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

    def mput(self, data_set):
        for i in data_set:
            self.put(i)


class MemoryQueue(MultiQueueMixin, queue.Queue):
    pass


def get_queue(config):
    queue_engine = config['QUEUE_ENGINE']
    queue_size = config['QUEUE_MAX_SIZE']

    if queue_engine == "server":
        replay_queue = MemoryQueue(queue_size)
        command_queue = MemoryQueue(queue_size)
    else:
        replay_queue = MemoryQueue(queue_size)
        command_queue = MemoryQueue(queue_size)

    return replay_queue, command_queue

